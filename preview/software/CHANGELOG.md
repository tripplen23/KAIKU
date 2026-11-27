# Changelog

**One history for the whole system** — `ais_recorder/` (the writer) and
`custody_mvp/` (the reader). They are one system: separate changelogs are how
their two ideas of where the store lives went unnoticed for 4.6 hours.

What changed and why. Usage lives in [MANUAL.md](MANUAL.md); per-component
architecture in [custody_mvp/README.md](custody_mvp/README.md) and
[ais_recorder/README.md](ais_recorder/README.md). **▸** marks something the
system itself found — a number that decides something.

---

## 2026-11-26

**Added — the project declares its dependencies, and builds its own environment**
- `software/requirements.txt`: the two packages that are not standard library,
  pinned. `h3` for the hexagons of `gps_interference`, `paho-mqtt` for the MQTT
  AIS ingest. `requirements-dev.txt` adds the three the tests need.
- `software/venv.sh` builds and updates the environment, on demand and by hand:
  `./venv.sh`, `./venv.sh dev`, `./venv.sh where`, `./venv.sh rm`.
- The environment does **not** live in the repository: binaries compiled for
  this machine, which do not travel and which Dropbox has no room for. It lives
  where `rutas.toml` now says (`[entorno] venv`, relative to `datos`), beside
  the rest of what is regenerable. What travels is `requirements.txt`.
- `custody.sh` resolves the interpreter through `rutas.venv()` and falls back to
  the system `python3` when there is none; `./custody.sh status` opens with
  which of the two it is using and whether `h3` imports.
- `gnss_leo_recorder/requirements-verify.txt` is gone: its three pins moved to
  `requirements-dev.txt`. One project, one place where dependencies are named.

**▸ Added — `gps_interference_coverage`: the outline of what GPSJAM actually saw**
- The hexagon layer only ever drew cells **with** a degraded aircraft, so an
  empty cell was ambiguous: good GPS, or nobody looked? The new layer draws the
  perimeter of the cells with at least two aircraft that day — dashed, no fill,
  under the hexagons — and the ambiguity is gone.
- For 2026-11-25: **1,353,795 km², 81 % of the AOI, in 6 pieces**. The other
  **19 % was never measured** — Gulf of Bothnia and open Baltic, where airliners
  do not fly. Of what was measured, 36 % by area had some degradation.
- Area is summed cell by cell (`h3.cell_area`), not taken from the 1,770 km²
  average: at 66 °N a resolution-4 hexagon is visibly smaller than at 53 °N.
  The outline overshoots the AOI by up to ~11 km, because a cell enters by its
  centre and is drawn whole; not clipped, the error is smaller than one cell.

**▸ Fixed — `gps_interference` builds again: 338 hexagons**
- The layer had been empty since the `.venv`s were deleted by hand on 2026-11-24
  (`GPSJAM: No module named 'h3'`), taking the build from 24/26 layers to 23/26.
  Nothing in the project declared that dependency, so nothing could notice. It
  does now, and the layer is back: 338 cells of ~1,770 km² with at least one
  degraded aircraft, out of 1,006 in the area, for 2026-11-25.
- The MANUAL called `h3` "the only dependency in the whole project" (§2f-ter).
  It was never true — `paho-mqtt` was the other one. Corrected, and both are
  named in one place, the new §1b.

---

## 2026-11-24

**Changed — the whole project left Dropbox, and nothing is installed on the machine**
- Dropbox ran out of space. `space_startup/` moved from `~/Dropbox/2026/` to
  `~/Documents/`, and the two generated stores were grouped beside it, out of the repo:
  `~/Documents/space_startup_datos/{custody,gnss_leo}`. Same filesystem, so the move was
  a rename, not a copy.
- **▸ 1.43 GB of the 4.1 GB was the same bytes twice.** Every file under
  `iteracion_06/.../02_cto_datos/fuentes/` had a sha256-identical twin in the recorder's
  own `gnss_leo/raw/`: research had re-downloaded what the pipeline already held. The 60
  duplicates were deleted after matching each hash at deletion time; the 45 files that
  existed only there (56 MB of literature and SAT-JAM JSON) were kept.
- `custody.toml` `cache`/`data` and `gnss_leo.toml` `raw_root` repointed, and **their
  comments rewritten**: they still explained which store sat inside Dropbox and why,
  which was no longer true of any of them. Same for the MANUAL's *Synced* column, now
  *Backed up*, now **no** on every row.
- 45 files held the absolute old path; all rewritten. `PROCEDENCIA.tsv` was deliberately
  left alone: it records where a file came from on a date, which is history, not a path
  to follow.

**Fixed — one day of AIS recording was in Dropbox conflict copies, not in the file the app reads**
- ▸ **`locations-2026-11-21.ndjson.gz` held 882 records. The day had 513,919.** Dropbox
  cannot merge a gzip that a live recorder appends to, and a second machine was syncing
  the same folder, so each divergence became a *conflicted copy*: **103 of them for that
  one day**, while the canonical name kept 0.2% of the data. No error, no log line. The
  app had been blind to 21-Nov for three days. `vessels` and `polllog` for the same day
  were untouched — only the high-frequency stream was being appended often enough to
  collide.
- **The 103 copies were not redundant: 513,919 lines read, 513,919 unique.** Each copy held
  a different slice. Repaired by writing the union through the project's own
  `store._encode_member`, batches ordered by reception time, and installed only after
  proving set equality against all 104 sources: nothing invented, nothing dropped. Result
  verifies at 1,360 members, 0 truncated tails, 24 hours covered, 959 vessels.
- ▸ **Two `gnss_leo_record` extracts had the same wound**: `swarm_esa-2026-11-17.ndjson.gz`
  and its `.global` sibling were empty gzip stubs (55 and 62 bytes) while their conflict
  copies held 10,337 and 25,923 rows. Not merged — **re-extracted from the raw ZIPs**,
  which is the authoritative source, and the result came out **byte-identical** to the
  copies (same sha256). Independent confirmation rather than a promoted copy.
- All **245** conflict copies deleted, after proving each was contained: manifests
  compared by `url` + `sha256` (28 copies, zero provenance missing), summaries shown
  regenerable, state from the other machine discarded rather than merged.
- **The lesson, which is the opposite of the 2026-11-13 decision:** that day the AIS store
  was moved *into* Dropbox precisely because it is irreplaceable. A live writer and a file
  synchroniser cannot share a directory, not even to protect it. A day is backed up once
  it is **closed**, not while it is open.

**Added — the build says where it writes, at the start and at the end**
- Three directories were only discoverable by reading `custody.toml`. After moving the
  stores three times in one day, the log is the first place anyone looks, so it now opens
  with the build output directory, the network cache, and **which config file said so**.
- It closes with what it left: file count and megabytes in the output directory, repeated
  in the summary block. Size on disk is what exposes a layer the manifest calls `ok`
  because it wrote a FeatureCollection with no features — 0 B does not exist, 180 B does.

**Changed — the repo is back in Dropbox, and the project is self-contained again**
- `space_startup` moved back to `~/Dropbox/2026/`, 400 MB of code and text, to get its
  backup back. The research and data trees stay in `~/Documents`, outside the cloud.
- ▸ **The path config was in the wrong place and that was a real mistake.** It had been
  put in `~/.config/space_startup/`, which made the project depend on a file sitting
  loose on this machine — the opposite of portable. It now lives at `<repo>/rutas.toml`
  with its resolver beside it, and the research tree's root carries a **one-line**
  `rutas_enlace.toml` naming the repo. Two pointers, both inside a project, nothing on
  the machine: copy the folders to another machine and it works.
- `repo` was dropped from the config entirely — it is derived from where `rutas.py` sits.
  A path the code can work out is not configuration.
- Moving the repo to Dropbox needed exactly **two edited lines**, which is the whole
  point of the exercise. Verified after the move: all 8 roots resolve, and **23 of 23
  paths the scripts ask for exist**.
- Two scripts had the bootstrap land *after* their first use of it, because they extend
  `sys.path` before importing project modules. Caught by checking import order against
  first use, with comments excluded — the first version of that check flagged all twelve
  by matching its own comment text.

**Changed — research split into its own repo, and no path is hardcoded any more**
- The six `investigacion/` trees (1.4 GB, 70% of the repo's weight) moved to
  `~/Documents/space_startup_investigacion/`, keeping their path inside it so a
  reference still reads the same. `space_startup` went from **4.1 GB to 400 MB**, which
  is the point: it has to fit in Dropbox again.
- ▸ **The real cost was not the move, it was doing it three times.** Each relocation
  today meant rewriting the same absolute paths in the same scripts. They now read
  `~/.config/space_startup/rutas.toml`, one file naming the three trees and each store;
  **16 analysis scripts and one test lost every absolute path they carried.** A move is
  now one line of config, not a sweep.
- Four scripts did not need config at all: they hardcoded *their own* folder, now derived
  from `__file__`. Config is for what a script cannot know; its own location it can.
- `gnss_leo_recorder/tests/test_parsers.py` built its fixture path by walking up to
  `canal/`, which no longer holds research. Repointed through the same config: **25 tests
  pass**, fixtures found in the new tree.
- The resolver fails loudly — a missing root or an unknown store name exits with the name
  and where to fix it, instead of returning a path that does not exist. That is the same
  lesson as `record_fallbacks`: a configuration error must not become silence.

**Changed — every store the app reads now lives in one directory, none inside the repo**
- `ais_record/` (91 MB) and `gnss_leo_record/` (110 MB) moved out of `space_startup/` to
  join `custody/` and `gnss_leo/` under `~/Documents/space_startup_datos/`. The repo is
  now code and text only, 2.6 GB of it.
- **The criterion changed and the comments now say so.** Until today each store sat where
  its *recoverability* put it, because that decided what Dropbox synced. With nothing
  synced, that split bought nothing and cost a rule nobody could state in one line. The
  division is now by nature — repo is code, `_datos` is data — so one directory can be
  versioned or pushed to a cloud whole and the other excluded whole, with no per-file
  decisions. Which of the four is irreplaceable is documented inside, where it is needed:
  only `ais_record`.
- Both previous homes of the AIS store were added to `record_watch`, which is what that
  list is for: they are **watched, never read**, so a recorder started against a stale
  config is reported instead of silently splitting the archive in two.
- 15 files of code, config and documentation repointed. Run outputs, logs and
  `gnss_leo_record/state.json` were left alone: they record where a past run wrote, which
  is history. `state.json` still names the old extract root and will be correct after the
  next manual run.

**Removed — the `gnss-leo-recorder` systemd unit**
- Stopped, disabled and deleted from `~/.config/systemd/user/`, at the owner's request:
  nothing of this project is to be installed on the machine. It is started by hand now,
  from the terminal. The unit file is kept in the repo as
  `gnss_leo_recorder/gnss-leo-recorder.service.ejemplo`, not installed.
- **The cost is real and is the point of a recorder:** nothing restarts it after a crash
  or a reboot, so an archive gap is now a gap nobody reports. `gnssctl.py status` lists
  incomplete days, and Spire keeps ~10 days upstream, so a gap caught inside that window
  can still be filled. Outside it, it is lost. This is the same failure that cost the AIS
  recorder 4.6 hours on 2026-11-13, now reintroduced on purpose.

---

## 2026-11-20

**Added — `gnss_leo_recorder/`, a second recorder: navigation receivers in orbit**
- Downloads and keeps the free observation files of **Spire** (bought by NOAA, served by
  UCAR), **Swarm A, B, C** (ESA) and **Sentinel-6A, -6B** (EUMETSAT), and extracts their
  signal-strength observables (carrier-to-noise, RINEX `S`) for every epoch over the
  Baltic box and a control box at the same latitude over Canada. CEO decision 1 of
  iteration 06; the CTO's test reads it. Records only: no interpretation, no detection.
- Runs as a **systemd user service from the first day**, `Restart=always`: the AIS
  recorder died with a laptop reboot; this one starts with the session. Linger left to
  the owner (MANUAL Part 0-bis).
- Standard library only. One module per source, each cycle isolated: Sentinel-6 is
  disabled (no account) while the other two record.
- ▸ **Measured on the backfill from 2026-11-09:** Spire 10 days, Swarm 7 (Swarm publishes D+4), no gaps.

  | | raw MB/day | receivers | epochs/day (unique) | box rows/day Baltic · control | extract MB/day box + global |
  |---|---|---|---|---|---|
  | Spire | 95.0 | 21 | 618,786 | 5,007 · 13,363 | 0.97 + 4.47 |
  | Swarm | 95.0 | 3 | 259,163 | 3,965 · 6,230 | 0.75 + 2.38 |
  | orbits (IGS + GFZ) | 0.8 | — | — | — | — |

  191 MB/day raw, 8.6 MB/day into Dropbox; 61.6 GB free gives 244 days before the floor.
  13-Nov, the day of the samples: Spire 4,991 Baltic and 13,042 control rows, Swarm 3,940
  and 6,193.
- Raw outside Dropbox (`~/Documents/gnss_leo`), extract and manifest inside it. Manifest
  line per file: url, bytes, sha256, HTTP code, content type, reception time, licence,
  terms URL. Nothing is deleted; below 15 GB free, raw downloads stop with a CRITICAL
  banner. One writer per store, `flock`, as in the AIS recorder.

**Added — our own Compact RINEX decoder, checked against the reference**
- Spire publishes Hatanaka-compressed RINEX 2.11. The usual decoder is C fed with
  untrusted bytes; ours is ~100 lines of Python that decode straight to values.
- ▸ Value by value against the pinned C reference (`hatanaka==2.8.1`, in `.venv`, tests
  only) on every non-empty Spire file of 13-Nov: **298 files, 875,661 epochs, zero
  differences**. CRINEX 3 by round trip through the reference compressor.
- Downloads are read in memory member by member, never unpacked to disk; names
  validated, links skipped, 1 GiB decompression fuse; `python3 -I` throughout.

**Found — what the files actually contain**
- ▸ **Swarm's `S1W` and `S2W` are one number written twice**: identical in 637,454 of
  637,454 pairs on 13-Nov (Swarm A). `S1W` takes a constant −3.68 when L2 is lost, 1.3 %
  of the day. Only `S1C` is a clean C/A carrier-to-noise; two frequencies are not there.
- ▸ **Spire's `S1`/`S2` are `S1C`/`S2L`** (the header records the RINEX 3 → 2 conversion;
  the extract maps them back). About 1 value in 12,000 is non-physical, −164 to +338
  dB-Hz. Stored literally; filtering is analysis.
- ▸ **1.3 % of Spire epochs have no orbit**: passes published without `leoOrb`. Counted,
  not guessed. Two of 300 Spire files of 13-Nov are empty.
- **Sentinel-6 has no position in its RINEX and EUMETSAT no open orbit product** (none
  among 197 Data Store collections). The orbit is the laser-ranging prediction EUMETSAT
  issues daily, open on EDC, 180 s step. ▸ 9th-order interpolation reproduces Swarm's 1 s orbit to
  1 cm from a 60 s step (Spire's) and 0.37 m from 180 s. Which `S` observables Sentinel-6 writes is
  only visible inside the file: `[VERIFICAR]` with the first one.
- UCAR also offers `leoAtt` (attitude, ~80 MB/day), `opnGns` (~2 GB), `conPhs` (~1 GB),
  `podTec` (~545 MB): not taken; attitude is one config line away.

**Added — at the CTO's request, same day (`canal/iteracion_06/02_cto_datos_abiertos.md` §7)**
- The CTO found the drop over the Gulf real but dominated by a source near 51 N 36 E whose
  horizon also covers Norway: the comparison needs baselines from everywhere, not two boxes.
- **Global series at 0.1 Hz**: one epoch per receiver per 10 s, everywhere, with position
  (null when the orbit is missing). ▸ 6.9 MB/day (Spire 4.5, Swarm 2.4), ~88,000 rows a day; with the boxes, 257 MB a month into Dropbox. The CTO estimated ~6.
- ▸ **Repeated epochs dropped, and counted.** Spire's pass files overlap: on 13-Nov
  **255,666 of 875,661 epochs (29.2 %)** were the same receiver at the same instant, all
  but 101 identical. The box rows had been counting them: Baltic rows for 13-Nov go from
  7,963 to **4,991**, control from 17,420 to **13,042**. The summary carries
  `duplicates` and `duplicates_conflicting`; first read kept. Extractor version 2: every
  held day re-extracted by itself.
- **Navigation-satellite orbits, daily** (`igs_orbits`): IGS rapid (GPS only — IGS's
  rapid combination has no Galileo) and GFZ rapid (GPS, Galileo, GLONASS). ▸ 0.78 MB/day.
  Stored for elevation; elevation is not yet in the rows (pending, MANUAL Part 0-bis).
- **SAT-JAM nightly** (`satjam`): DTU's 9 public JSON, ▸ 20.9 MB a night. A snapshot —
  only today's exists — so a missed night is lost. No licence published: internal
  reference, cited.
- **`opnGns` refused in code**, even if someone adds it to the config (~2 GB/day).

**Licences — Compliance's conclusion (`canal/iteracion_06/07_compliance.md` §A)**
- Spire-NOAA: commercial use, raw and derived redistribution, yes. NOAA's current order
  delivers until **2026-12-01**; after that `[VERIFICAR]`. ▸ The recorder logs
  `NO NEW FILES` once no new Spire day arrives for 3 days.
- Swarm: commercial use with an ESA account. **Raw never redistributed openly**; derived
  yes, «© ESA». Sentinel-6: Copernicus, free use and redistribution.

**Tests**
- `tests/test_parsers.py`, 25 tests, ~50 s, on the real 13-Nov samples kept in `canal/`:
  decoder against reference, headers, orbits and interpolation, end-to-end extraction of
  Spire and Swarm with exact row counts, a synthetic Sentinel-6 hour placed over the
  Baltic with the real prediction, repeats and the 0.1 Hz series, archive traversal,
  decompression fuse, disk floor, lock, stale upstream, `opnGns` refusal, SAT-JAM snapshot. `GNSS_LEO_FULL_TESTS=1` checks all 300 Spire files (~80 s more).

---

## 2026-11-14 (d)

**Added — interference with satellite navigation, a new group of two layers**
- IND-07 fires on a position jump, and there are two explanations it cannot choose
  between: a tampered transponder, or an interfered receiver. This group is what
  separates them.
- ▸ **GNSS-Finland, and it measures *now*.** 47 reference stations of the FinnRef
  network, **33 inside the area of interest, eight along the Gulf of Finland** —
  Virolahti sits at 60.54 N 27.54 E, on the border. Carrier-to-noise per signal and
  constellation, **a new reading every 30 seconds**, 15-degree elevation mask. The
  only source in the whole tool that answers "right now" for interference.
  - The data interface is **documented nowhere**: port 8080, found by watching what
    the service's own page requests. `api/capabilities` gives the stations with
    coordinates, the receiver thresholds (GPS L1: good ≥ 40 dB-Hz, poor < 37) and the
    three-level scale; `api/sigstatus` gives the live state. No credentials.
  - **The worst signal wins, never the average.** Interference hits one band, almost
    always GPS L1 because that is the one worth attacking; averaging it with four
    healthy constellations erases it.
- ▸ **GPSJAM, and it is context, never proof.** 48,244 cells worldwide for 2026-11-12,
  **1,019 inside the area, 316 with at least one degraded aircraft**; strongest is
  56.0 N 22.3 E at **10 of 17 aircraft degraded**, the Kaliningrad corridor. Four
  limits printed on the layer: it aggregates a **whole day** (five minutes of
  interference paints 1,770 km² for 24 hours, so against a second-stamped AIS jump it
  is a weak coincidence, not a correlation); it arrives **2 days late** (measured: the
  13th was still 404 on the 14th); it is **blind where aircraft do not fly**, which
  over the open Baltic is most of it; and an aircraft at 10 km does not see what a ship
  20 miles offshore sees.
  - Cells with one aircraft all day are dropped — 61 of them. One degraded out of one
    is 100 % on a sample of one: noise shaped like signal.
  - Needs `h3`, **the only dependency in the project and optional**. Without it the
    layer is empty and says so.

**Added — a third licence state, because silence is not prohibition**
- ▸ Neither source publishes terms. That is **not** HELCOM's depth contours saying
  *"any commercial use is prohibited"*. Treating silence as prohibition throws away
  useful public data; treating it as permission is how you sign a contract you cannot
  honour. `ask_before_selling = true` passes the check and is **listed at the end** so
  it cannot be forgotten, while an explicit prohibition still fails the build.

**Answered — are navigational warnings consumable, or only text?**
- ▸ **There was an interface and it is gone.** `/api/v1/nautical-warnings/*` on
  Digitraffic Marine is on the November 2022 deprecated list; the current specification
  has 18 paths and none is warnings. Confirmed with a request: 404. The replacement,
  **Vilkku**, is being built by Traficom and Fintraffic on the **S-124** standard,
  announced for early 2026 and not confirmed in service. Today warnings go out over
  NAVTEX and VHF: broadcast text. The source with the most legal authority on the list
  is the least integrable — and Traficom is on the hackathon expert list.
- Traficom's interference statistics are annual national totals in narrative form: a
  citation, not a layer. Two breaks in the series recorded, because quoting across
  either would be wrong: aviation criteria narrowed 1 May 2024, and from 1 January 2026
  the maritime count changed from *reports* to *vessels affected*.
- **Found while looking:** `/api/aton/v1/faults` on the same Fintraffic interface we
  already use for AIS — **88 open aids-to-navigation faults**, with position, fairway
  and how long they have been out; one unlit since October 2023. CC BY 4.0, no key. Not
  interference, but the same kind of context: an unlit beacon beside a cable corridor
  explains an odd track without needing a malicious explanation. Noted, not yet built.

**Changed — fewer acronyms**
- Interface, manual and changelog now spell out technical terms. Common ones stay (GPS,
  AIS, radar); descriptive abbreviations get their words back. A jury that is not from
  the domain should not have to translate.

---

## 2026-11-14 (c)

**Fixed — the radar mosaic was mostly 410 Gone, and nothing said so**
- ▸ **We were caching the identifier of a temporary resource.** `/mosaic/register` does not
  return data: it returns the id of a mosaic Planetary Computer creates on its side and
  **expires in hours**. Our STAC cache held it for **6 h**, so past that every tile answered
  `HTTP 410 Gone`. Measured: **58 % of tiles failing** with a three-hour-old id served from
  our own cache — 27 ok against 37 errors at z7, 70 against 170 at z6. The radar simply
  vanished from the map and the only clue was a 502 body nobody reads.
- The registration is no longer cached (`ttl=0`); an ordinary STAC search still is, because
  that one returns data. Plus two guards, because any lifetime guess eventually breaks: the
  client rebuilds its template after 20 minutes, and **re-registers when the failure pattern
  gives away a dead id** — over half a batch failing, not one tile, since a single tile over
  sea with no recent pass can fail legitimately.
- After the fix, at the same zoom: **96 tiles, 96 ok, 0 errors.** At z6: 168/168.

**Changed — Sentinel-1 is on by default, in mosaic mode**
- Radar is the layer that answers the product's question, so starting it off cost three clicks
  before anything appeared. `follow: false` puts it in mosaic mode: most recent pass
  everywhere, rather than one scene at one instant. Sentinel-2 stays off — optical is useless
  at night and under cloud, which above 60°N is most of the year.
- ▸ **A layer can no longer be "on" without being switched on.** `on: true` only ticked the
  checkbox; nothing called `imgOn()` at load, so the layer sat armed and inert and the only
  way to see it was to untick and retick. The config now drives the checkbox, not the HTML.

**Added — an on-map note when a layer is on but the zoom suppresses it**
- ▸ The tiler renders no mosaic below **zoom 8**: z3–z7 answer `204 No Content` whatever the
  tilejson's `minzoom` says (it claims 0). Below z8 Leaflet scales z8 tiles, and each level out
  quadruples the count: **96 at z7, 168 at z6, 241 at z5**. z5 does not fail — it takes minutes
  and looks like a chequerboard, 28 % loaded after 60 s. So the floor stays at z6, now with the
  measurement behind it rather than an estimate.
- At z5 — the opening view — an amber note on the map says the radar is on and one scroll away,
  instead of a ticked box over an empty sea with the explanation buried in the Layers tab.
  **Sticky**: it stays while the condition holds. A six-second flash is for events, not states.

**Added — the CFAR explanation is reproducible, and the false-alarm arithmetic is written down**
- `python3 -m custody.sardetect --demo` runs the real `cfar()` against a synthetic sea, calm on
  one side and rough on the other, with the same ship in both. No global threshold finds both:
  at 120 the rough half gives **1,890 false pixels**, at 450 **neither ship**. CA-CFAR finds
  both with zero false alarms, from two thresholds **3.3× apart** it computed itself.
- `false_alarm_rate(k, model)`: at `k=6`, **1.5·10⁻⁶ per pixel** under Rayleigh clutter — about
  6 pixels in a 2000×2000 crop. Assuming Gaussian instead gives 9.9·10⁻¹⁰, **1,479× lower**. The
  clutter model moves the answer more than the threshold does, and real sea has heavier tails
  than Rayleigh, so the operational number has to be asked, not derived.
- The manual now carries the ring diagram, **why the guard band exists** (without it the ship
  enters its own background and hides itself, worse the bigger the vessel), both tables, and the
  assumption stated out loud. It had the concept and the 55 m validation but not the reasoning.
- Five checks in `test_runtime.py` keep the explanation true rather than just stored.

---

## 2026-11-14 (b)

**Changed — the Layers tab: one catalogue, collapsible groups, two axes, search**
- ▸ **66 toggleable layers were four flat lists in one scroll**, rendered from four places
  — `app.js` for the build's, `marine.js` for Copernicus Marine's 22, `emodnet.js` for
  EMODnet's 12, and eight written by hand in `index.html` — with three separate grouping
  loops doing the same job. Finding one meant reading all of them.
- One catalogue now, one renderer. **Three clicks to anywhere**: tab → open group → tick.
  Search cuts it to one click plus two letters and auto-expands what matches, because
  hiding a result behind a triangle is the opposite of searching. It matches name,
  explanation *and* source, so `cable` returns the OSM corridors and EMODnet's telecom and
  power cables together — 10 hits across two providers that share no name.
- **Two axes over the same catalogue**: *by purpose* (default, 9 groups — an operator looks
  for "the cables", not "the EMODnet ones") and *by source* (10 groups — provenance and
  licensing). Switching changes one grouping key. Axis and open groups are remembered.
- Each header shows how many layers it holds and **how many are on, while closed** — the
  thing that stops you opening nine groups to find the one you left enabled. Plus
  **Turn all off**, because switching layers on is easy and remembering which is not.
- A third level only where it earns it: the 22 forcing layers split by Copernicus dataset.
- Provenance and licence stated once per group instead of per layer.

**Fixed — a layer credited to the wrong organisation, on the one dropped for its licence**
- ▸ Grouping by source made it visible immediately: the isobaths were labelled **"Depth
  contours 10/20/50/100 m (HELCOM)"**. They are ours, derived from the EMODnet DTM — and
  HELCOM's own contour layer is deliberately **not used because it prohibits commercial
  use**. Crediting the wrong party on exactly that layer is the most expensive mistake a
  label can carry. The levels were wrong too: 20/50/80/100.
- A check now fails if any layer name credits a source that is not its own. Verified it
  can fail by putting "(HELCOM)" back.

**Fixed — layers the build did not produce rendered as empty rows**
- `gfw_events` and `gfw_grid` left two blank slots, indistinguishable from the layers not
  existing. They now appear disabled with the build's literal reason — *"GFW_TOKEN missing
  from secrets.env"* — which is the same rule the Health panel already follows.

**Fixed — the DOM stub returned a new node per `getElementById`**
- ▸ `getElementById: () => el()` handed back a different double every call, so writing
  `innerHTML` on one was invisible from another lookup of the same id — **any check on what
  a panel actually renders came back empty**. A browser returns the same node; the double
  does now. This is what let the layer-panel check assert the rendered HTML rather than the
  intention.

**Tests**
- The classification check used to walk `LAYER_GROUPS`, which only knew the build's layers:
  half a classification, with 42 others outside it. It now walks the whole catalogue —
  66 layers, no duplicates, both axes complete, nothing on the map missing from the panel,
  no empty rows, no mis-credited names, and neither axis allowed to dump more than half the
  layers into one group.
- Eight rows carry their own listeners and state (the Sentinel cursor followers, the HELCOM
  coastline status, the WMS legends). The panel **moves** those nodes into place instead of
  re-creating them; recreating them would silently detach the listeners, and the symptom
  would be "the checkbox stopped doing anything".

---

## 2026-11-14 (a)

**Done — the stores are actually one now**
- ▸ Recorder stopped cleanly, final merge, restarted against the configured root:
  **1,096,520 records in one store**, gzip CRC clean on every file, a control dry-run
  copying zero. The last pass moved 11,190 records written while the earlier merge ran —
  which is the point of the tool being idempotent rather than a one-shot.
- The recorder resumed onto the merged file without duplicating or losing anything
  (`resume: 340594 records already in locations-2026-11-13.ndjson.gz`), and its first
  log line now states the root and where that root came from.
- `~/ais_data` **moved aside, not deleted**, to `~/ais_data.merged-2026-11-13`. It is
  primary observation; deleting it is a decision for a person, after the dry-run reads
  zero. `python3 -m custody.paths` reports no strays.

**Fixed — `custody.sh` was the launcher overriding both paths, and that was the real cause**
- ▸ `DATA="${AIS_DATA_ROOT:-$HOME/ais_data}"` on line 16, then `--root "$DATA"` passed to
  the recorder. **This launcher was the third opinion on where the data lives, and the one
  that won.** Fixing `recorder.py`'s default achieved nothing while `./custody.sh up`
  overrode it — this is the concrete reason the recorder was writing to `~/ais_data` on
  2026-11-13 while the app read Dropbox. It now asks `custody/paths.py`, and passes
  `--root` only when `AIS_DATA_ROOT` is explicitly set.
- ▸ Same bug at the other end: the build output was hardcoded to
  `custody_mvp/viewer/data`, so `./custody.sh status` reported **"no build yet"** over a
  79-file build. Now `built: 2026-11-13T15:47:19+00:00 · layers ok: 22/24`.

**Changed — one manual and one changelog for both components**
- `MANUAL.md` and `CHANGELOG.md` moved up to `software/`, covering the recorder and the
  viewer together. Each component keeps its `README.md` for its own architecture and
  points up; no fact lives in two places.
- New **Part 0** in the manual: running the recorder, the systemd unit, what it writes,
  and how to query it — folded in from `ais_recorder/README.md`, which was the other
  copy of this material.
- ▸ **Deleted a recommendation that had become wrong.** The recorder README said the
  store was "inside Dropbox, ~19 MiB/day of sync traffic — move it out". That advice
  predates the storage model and inverts it: the recording is the *only* thing that
  must be backed up, and the 1.9 GB of regenerable tiles are what should not sync.
  Stale advice in a manual is worse than no advice.

**Tests**
- ▸ A check that **no file in the tree writes a store path by hand** — the only legitimate
  place is `paths.py`, which is the single source. Verified it can fail: putting
  `DATA="${AIS_DATA_ROOT:-$HOME/ais_data}"` back into `custody.sh` makes it report
  `custody.sh:48`. 35 files clean.
- It ignores comments *and* docstrings, because the prose that explains the bug quotes the
  old path deliberately; a check that confuses documentation with code teaches you to stop
  documenting.
- Plus checks that the launcher asks `paths` for both roots and does not impose `--root` on
  the recorder unless asked. 28 runtime checks in total.

**Removed — the launcher's last-resort guess**
- If `paths` cannot be read, `custody.sh` now **stops and says so** instead of falling back
  to `$HOME/ais_data`. A fallback default there is literally the second opinion that caused
  the incident; failing loudly is the correct behaviour for a broken config.
- `build.py --ais-root` help text still advertised `(AIS_DATA_ROOT, ~/ais_data,
  ../ais_recorder/data)`. Stale help is a wrong answer with an authoritative tone.

**Added — a warning that says whether anything is still writing**
- `stray_records()` now reports the newest write time and an `active` flag. "Recording
  found in a folder nobody touched for days" and "a recorder is writing there right
  now" need different answers: the first is cleanup, the second means merging is not
  enough and the recorder has to be pointed at the declared store.

---

## 2026-11-13 (n)

**Changed — one store, declared in one place, and the recorder reads it**
- ▸ The recorder's default root was `<its own dir>/data` and nothing else, so writer
  and reader each had their own idea of where the store lives. It now reads
  `paths.record` from the same `config/custody.toml` the app does. It still works
  standalone, but then it **says** which fallback it used instead of inventing a path.
- A `--root` that is not the configured one now logs a warning with the merge command.
  Not blocked — it may be deliberate — but no longer silent.
- ▸ **`record_fallbacks` is gone.** A list of places to *look* turns a configuration
  error into silence, which is how 4.6 h went invisible. Replaced by `record_extra`
  (empty; only for a read-only historical archive) and `record_watch` — places that
  are **watched, not read**. Recording found there is reported in the Health panel,
  in `/alerts/status` and in `python3 -m custody.paths`, with the command to merge it.

**Added — `ais_recorder/merge_store.py`, and the stores unified**
- ▸ **960,446 + 124,884 = 1,085,330 records**, gzip CRC clean on every file, 129
  records correctly recognised as already present, second pass copying zero.
- **Does not need the recorder stopped**, because the format already works this way:
  each batch is an independent gzip member appended to the file, so merging is the
  store's native operation. A batch half-written in the source is just not copied yet.
- **Idempotent** on natural identity per stream, so it can be re-run after the
  recorder has written more. **Does not delete the source** — primary observation, a
  person decides.

**Added — EMODnet Human Activities: the traffic baseline for the whole AOI**
- Our receivers cover 21 % of the AOI. Over the rest the tool could not say whether
  what it saw was unusual, because it had no idea what usual looks like there. 12
  layers, 1 km cells, covering 100 % of the AOI from AIS we do not have.
- ▸ **Two products, and the gap between them decides which is usable.** Route density
  is built by **EMSA** from the EU's own AIS and reaches **2026-10** — one month
  behind, so it is the operational baseline. Vessel density is built by **Cogea** from
  AIS *purchased* from CLS, ORBCOMM and vesseltracker.com, reaching only **2024-12**,
  but split into thirteen ship types including *Military and Law Enforcement*, which
  EMSA does not break out. One is the present, the other the climatology.
- ▸ **The caveat the service publishes itself**, repeated in the panel because it
  decides a comparison: in 2024 its AIS provider lost satellite data from June, so
  H2 2024 is thin. Compare a November against 2023.
- Also the **official EU aggregation of cables** (telecom and power, separately),
  pipelines and wind farms. Ours come from OpenStreetMap, which is community-mapped —
  for a product whose subject is the cable, this is the second opinion. Both drawn;
  neither replaces the other.
- ▸ **The instant is picked from the declared list, never rounded.** EMODnet
  enumerates each month; ask for anything else and the service returns an empty tile,
  which on the map reads as "nobody passes here" — the opposite of what the layer is
  for. The panel prints which month is drawn and how far it is from the cursor, amber
  past 45 days.
- Capabilities cached for one day, not forever: a new month appears monthly, and an
  eternal cache would freeze the baseline at build time — the FMI bug again.
- CC BY 4.0, commercial use permitted, attribution naming **both EMODnet and CLS**
  (the AIS was purchased, so that credit is not optional). In `config/licences.toml`.

**Added — Mercator Ocean's global current, as a declared cross-check**
- ▸ **Answering the question directly: the Baltic product is not Mercator's.** Mercator
  Ocean International operates the Copernicus Marine Service and produces its *global*
  products; the Baltic model this tool runs on is **SMHI's** (Baltic MFC, DMI as local
  service desk) — NEMO v4.0 at **1 nm**, 56 levels, twice-daily, six-day forecast.
- Adding the global model would be a **downgrade in resolution**: 1/12° (~8 km) against
  1 nm (1.85 km), and the Gulf of Finland is 50–100 km wide. It is in as a cross-check,
  in its own group, off by default, with the resolution printed on the layer.
- What it genuinely adds: **total velocity — Eulerian + waves + tide**, which is what
  transports a hull; the Baltic product publishes the Eulerian current only. Plus the
  tidal component alone, worth one look to confirm how little of the Baltic current is
  tide.
- Both pinned to the `merged-uv` dataset, because the usual picker takes the highest
  version tag and that selects the Eulerian-only dataset. Pinning is what the picker
  exists to avoid, so it is **checked**: a vanished dataset is reported as missing, not
  served as empty tiles.

**Tests**
- Smoke: the EMODnet catalogue is loaded into the test context and the absence of
  baseline lanes is always a failure; the two baselines must end more than 300 days
  apart (if they matched, someone had merged them); `emodPick` must return an instant
  the service actually declares.
- ▸ Two test messages were lying. One hardcoded "4 groups" and kept saying 4 after a
  fifth was added; it counts now. A new check fails if any lane name contains an
  internal key — `CMEMS currents_global` reached the screen that way.

---

## 2026-11-13 (m)

**Fixed — 4.6 hours of recording the application could not see**
- ▸ **`paths.record()` returned the first store that existed and ignored the rest.** The
  recorder was restarted with `--root ~/ais_data` while the configured root in Dropbox still
  existed, so the fallback was never consulted. The recorder wrote, the disk filled, and the
  timeline sat at **09:07Z** while the store ran to **20:19Z** — with no error in any log.
  `paths.records()` now returns them all and they are unioned, deduplicated by
  `(mmsi, timestamp)`. **794,388 → 1,034,082 fixes**, span now reaching the present minute.
- Same change in `build.py`, `/coverage` and the live engine, which all read the store.

**Fixed — 752 false IND-04 alerts from a recorder outage**
- ▸ The live engine passed the indicators `[(window start, now)]`: one continuous window,
  which asserts *we were listening the whole time*. IND-04 fires when a vessel stops
  transmitting **inside** coverage, so with the recorder down 6.5 h that assertion made one
  alert per hull: **909, all false. 157 with the real windows from the polllog.** The build
  had always applied this correction (T2); the runtime engine had not. `/alerts/status` now
  reports `window_h` and `coverage_h` separately and a test fails if they are ever equal.

**Fixed — the current layer was a 24-hour mean, sea level a 30-day mean**
- ▸ Copernicus publishes the same variable as 15-minute, hourly, daily and monthly series
  under one version tag. The picker compared version tags only, so between them it kept
  **whichever came first in the XML**. Now: newest tag, then **finest cadence**. Surface
  current and sea level go to **15 min**, waves and ice to **1 h**. Tiles and legends
  verified 200 on the new datasets.
- Each layer snaps the cursor to **its own** step instead of the hour, which was throwing
  away three quarters of the resolution on the 15-minute fields.

**Fixed — `net.fetch` had no TTL, so forecasts aged forever**
- ▸ "The file exists" was enough to serve it. For a forecast that is a silent, permanent
  error: FMI was returning a wave series ending **15:00Z** while the clock read **20:21Z**.
  A real-time tool serving a five-hour-old forecast is not late, it is wrong. `max_age`
  added; FMI set to 15 minutes. Coastlines and capabilities keep the permanent cache.

**Changed — the engine fires when data arrives, not when a timer expires**
- ▸ The loop slept 60 s between passes while the recorder also wrote every 60 s, so a fix
  could wait a full minute to be checked. It now stats the newest file of each store every
  3 s — **0.1 ms a check** — and evaluates the instant the signature changes. The delay
  stops being "up to 60 s" and becomes the evaluation itself.
- The window sizes itself to the build gap instead of being a constant 6 h. A fixed window
  with an 11 h build left **five hours with neither** build nor engine data. Floor 6 h
  (no indicator looks back further than 30 min), ceiling 36 h, and it **says** when capped.
  Cost: **7.0 s** for 11.9 h, 118,275 fixes, 722 tracks.

**Added — live vessels, so nothing in the viewer waits for a build**
- `/vessels/live` serves the engine's window as tracks, built with the **same**
  `ais.tracks_geojson()` the build uses — extracted from `build.py` so there is one
  implementation, because the viewer merges both into one `HIST` and two splitting rules
  would change a track's shape at the boundary.
- ▸ **107,141 fixes and 712 vessels merged past the build's edge**, so the slider, the
  snapshot, vessel history, the counts and the basin focus all cover the uncompiled stretch.
  The "run the build again" warning is gone because it is no longer true; what replaced it
  states the covered span, and the old warning still appears in the two cases where it is
  accurate — no engine, or a gap wider than the ceiling.
- ▸ **5.8 MB → 130 kB per cycle.** The full window is fetched once, then only the 30-minute
  tail; overlap is deduplicated by timestamp. Server gzips anything over 4 kB.

**Added — one timeline lane per source, in four collapsible groups**
- Answers "can I overlay these two layers at this instant", which previously had to be known
  from memory. **11 lanes**: our recording, the evaluated window, AISHub, both Sentinels,
  both FMI models, four Copernicus datasets, and one for everything with no time axis.
- ▸ **Every window is read from its service, never written here.** A hand-typed cadence goes
  stale silently — that is exactly how the daily-mean current happened. AIS from the
  polllog, Sentinel from STAC, Copernicus from the `time` dimension of its capabilities, FMI
  from the time axis of its own answer.
- Copernicus is grouped **by dataset, not by layer**: 20 lanes would be noise and redundant,
  since layers sharing a dataset share a time axis by definition. Four lanes instead.
- A line under the lanes counts how many time-bearing sources have data at the cursor and
  names them. Forecast is hatched; data outside the view shows `→` or `←` at the edge rather
  than an empty lane, because empty reads as "none" and this means "beyond".
- Fold state persists, because the panel repaints constantly and would otherwise reopen what
  you just closed — the bug the map key already had.

**Removed**
- `laneHtml()` in `time.js`, a second lane builder that only knew about AIS and the two
  Sentinels. Two constructors for the same lane is how one ends up showing something the
  other does not.
- Both "run the build again" sentences, deleted from the string catalogue rather than left
  unused — and a check fails if either comes back. The hollow-bar mark survives with a
  truer meaning: *coverage nobody has evaluated*, which is now the engine's edge rather
  than the build's, so it only appears when something is genuinely missing.

**Tests**
- `tests/test_runtime.py`, 17 checks, one per bug above: multi-store union, coverage not
  faked, window bounds, cache expiry, finest cadence. Each verified to fail on the old
  behaviour — the cadence fixture returns the daily mean under the previous rule.
- Two viewer checks: live tracks appear in the snapshot three hours past the build and do
  not duplicate on re-merge; the lanes build, group, fold and discriminate by instant.
- ▸ One of them **passed vacuously at first** — it reported "0 CMEMS lanes" and moved on,
  because the catalogue was never loaded into the test context. Now the absence of lanes is
  always a failure.

---

## 2026-11-13 (l)

**Added — colour scales for every Copernicus Marine layer**
- ▸ **Twenty layers of colour with no scale said nothing**, which is exactly what was
  reported. All 20 now carry one, **served by Copernicus itself** rather than redrawn here,
  so the scale and the tiles cannot disagree. They show the variable, the units and the
  range: *Sea water velocity (m s⁻¹) 0–0.5*, *Significant wave height (m) 0.2–1.8*.
- ▸ **The legend URL is read from the capabilities, not constructed.** Building it by hand
  returned 400: the style has to be exact (`cmap:amp`, `cmap:thermal`, `cmap:haline`…).
  The service declares a `<Style>` with its `LegendURL` for every layer — 166 in the wave
  product alone. Two traps in that declaration: the `FORMAT` comes **double-escaped**
  (`image%252Fsvg%252Bxml`, where `%25` is a `%`), which is a 400; and the endpoint accepts
  **only SVG** — `image/png` is a 400 too.
- ▸ **The style now goes on the tile as well as the legend.** It did not before, and that
  is worse than having no scale: a legend describing one palette beside tiles painted in
  another. A check fails if the two ever differ.
- ▸ **The three vector layers were silently losing their scale.** Current and ice drift
  have styles named `cmap:speed,vectorStyle:solid`, and the style picker was skipping
  anything with a comma — so the most important layers were the three without a legend.
  Fixed, and it now prefers **`solidAndVector`**: colour for magnitude *and* arrows for
  direction, because for a current the direction is the point.

**Added — the AISHub aggregate client**
- The full client is written and **wired into the live engine as a second AIS source**,
  deduplicated against our own feed by `(mmsi, timestamp)` — the two networks hear the same
  hull in the same place, and counting it twice would distort both density and any
  indicator that looks at gaps. Rate limit of one request per minute enforced client-side.
- ▸ **It cannot run yet, and not for a licence reason.** Verified on 2026-11-13: the API
  answers **200 with zero bytes** both without a username and with an invented one. The key
  requires an approved contributing receiver. The engine reports this honestly in the alert
  panel — *Fintraffic 127,959 · AISHub idle (needs a key)* — rather than looking like it is
  working. The day the key exists it is one line in `secrets.env`.
- **The restriction that does apply**, recorded before anything is promised: the feed may
  be **used**, not redistributed. It may feed our alerts; it may not be re-served through
  an API of ours.

**Fixed (tests)**
- ▸ **A check asserted a line of source text and broke on a correct refactor.** It matched
  the literal comparison `tag > best[var][0]`; the dataset-tag selection still worked, it
  was just written differently. It now calls `_newest()` on a two-version fixture and
  asserts it returns the higher tag. A test that fails when correct code moves teaches
  people to ignore tests.

---

## 2026-11-13 (k)

**Added — Copernicus Marine, the forcing**
- ▸ **20 layers from the three Baltic products**, in five groups: currents, waves, ice,
  water column, and reanalysis for reconstructing past incidents. New `custody/marine.py`.
  This is what separates **drift from steering**: wind, wave and current produce exactly
  the picture IND-02 flags, so without them the indicator cannot tell one from the other.
- ▸ **The WMTS needs no credentials.** Verified on 2026-11-13: GetCapabilities and GetTile
  both return 200 and a 256×256 PNG. Raw data through OPeNDAP still needs an account — so
  the layers can be painted today, the numbers cannot be extracted.
- **Every layer follows the time cursor.** The current at the instant something happened,
  not the current now, which is half the point. Rounded to the hour: the products are
  hourly or daily, so asking for the exact minute breaks the tile cache without changing
  a pixel.
- ▸ **The dataset tag is chosen, not hardcoded.** Identifiers carry a version suffix
  (`_202411`, `_202611`) that Copernicus rotates each Service Release, and a URL with the
  old tag stops serving tiles without an error. The build picks the highest. Guarded by a
  check that fails if that selection is removed.
- **The 87° limit travels with the layer, not in a footnote.** Surface current direction
  carries that RMS error against seven moorings: it supports *"there was a current"*, not a
  computed drift. It is printed where the current layers are switched on.

**Added — FMI, and why it is not a proxy**
- `custody/fmi.py`: wind from HARMONIE and waves from WAM, open, no key, CC BY 4.0.
  **FMI is an original source here, not an intermediary**: those are its own models, and it
  provides *wind*, which Copernicus Marine does not publish because it is not a marine
  variable. The two are complementary.
- ▸ **`drift_explained` on IND-02 alerts.** Opening a crabbing alert now asks FMI for the
  wind and wave at that point and states whether the forcing explains the angle. Verified
  live: crabbing to the side the forcing pushes with 15.6 m/s wind → *explains it*;
  crabbing against it → **does not explain it, and that is the interesting case**. This is
  what turns IND-02 from a suspicion into evidence or a dismissal.
- Two measured traps are documented in the module: wave buoys return NaN from November
  (withdrawn before the ice season), and a point outside the useful grid returns NaN with
  HTTP 200 — absence has to be checked, not inferred from the status code.

**Added — AISHub coverage**
- ▸ **204 stations inside the AOI, 32 of them in the 56–60°N band where our own coverage
  dies** — including **Visby and Fårö on Gotland, beside the cables cut in November 2024**.
  The gap ones are drawn larger and amber, because they are the argument for requesting
  access rather than decoration.
- Station list only. The aggregated feed needs a contributing receiver, and **its
  redistribution is prohibited** — recorded in the licence register before anything is
  promised to a customer.

**Not integrated, and why**
- **Kystverket**: covers the Norwegian economic zone, not the Baltic, and **excludes
  fishing vessels under 15 m and recreational craft under 45 m** — so absence of a small
  vessel there is not evidence it was not present. The live feed goes through BarentsWatch
  and needs a registered client; the open NMEA stream at 153.44.253.27:5631 did not answer
  on 2026-11-13. Registered in the licence file with its scope and exclusions so the limit
  is on record.
- **aisstream.io**: deliberately excluded and recorded as non-usable. No licence, no terms
  of redistribution and no station list, so its coverage cannot be verified. Also worth
  recording: its `StandardSearchAndRescueAircraftReport` is AIS message type 9 — a search
  and rescue *aircraft* — not Synthetic Aperture Radar. The initials coincide and nothing
  else.

**Added (tests)**
- The marine catalogue must carry a dataset tag per layer, at least four groups, the
  current layer, and the 87° caveat; `marine.py` must still pick the highest tag.
- The AISHub layer must flag the gap stations and include Gotland.
- Both new sources had to be added to the licence register — **the licence test caught
  them on its first run**, which is what it is for.

---

## 2026-11-13 (j)

**Added — the indicators run at runtime, not only at build**
- ▸ **Alerts were computed only at build time, which makes a surveillance tool a reporting
  tool.** With a 42-hour-old build, "what is happening now" was answered with the day before
  yesterday. New `custody/live.py` runs **all seven indicators in the server**, every 60 s,
  over a rolling 6-hour window.
- **One engine, not two.** It calls the same `custody/indicators.py` the build calls. There
  is deliberately **no JavaScript reimplementation** — two copies of a detection rule is how
  the demo and the report stop agreeing, and this project has already paid for duplicated
  logic twice (the depth palette, the basin classification). A smoke check fails if the
  viewer starts computing thresholds, distances or dwell windows.
- **Push, not poll.** `/events` is a Server-Sent Events stream; the browser is told the
  moment a cycle finishes. Polling would add up to a minute of latency to a product whose
  value is firing *when* something is found. Also `/alerts/live` (GeoJSON) and
  `/alerts/status`.

**Measured — why a rolling window, and why 6 hours**
- Context (cables, bathymetry, port mask, vessel metadata) is static between polls and
  loads **once in 0.07 s**. The evaluation itself:

  | window | fixes | tracks | alerts | time |
  |---|---|---|---|---|
  | 1 h | 21,679 | 590 | 163 | **0.63 s** |
  | 6 h | 120,369 | 626 | 524 | **3.97 s** |

  Four seconds against a 60-second recorder cadence. Reading all 794,388 stored positions
  costs 4.4 s in I/O alone, and no indicator looks further back than its own window — the
  longest is IND-01's 30 sustained minutes — so evaluating recent hours gives the same
  answer for a fraction of the cost.

**Changed — how build and live alerts are merged**
- They overlap rather than concatenate, so the rule is by time: **before the live window
  the build wins** (it is the only one with long history), **inside it the live engine
  wins** (it is the only one with the last few minutes). Verified: 1,090 build + 513 live
  with no double-counted alert.
- The alert panel carries the engine's state: *LIVE · 513 alerts recomputed over the last
  6 h*, or a grey line saying alerts are build-only when the viewer is served without the
  proxy. New alerts are announced once, not every cycle.

**Fixed, found while building it**
- ▸ **The dedup key was too coarse for IND-06.** `(mmsi, indicator)` meant a vessel
  alongside **two different partners** counted as one encounter, so the second would never
  have been announced. Five such cases in the current window. The partner MMSI is now part
  of the identity.
- ▸ **Live alerts had no vessel names** — "MMSI 265048080 · type n/a", which is precisely
  what an operator cannot use. The engine was reading `vessel_info.json`, the enriched
  dossier, instead of the static AIS message-5 metadata from the store. **99% now carry a
  name and ship type.**

---

## 2026-11-13 (i)

**Added**
- ▸ **The coverage lane is live: it reads the store, not the build.** It came from the
  manifest, so it froze at the moment the build ran, and at 42 hours that reads as lost
  data. New `/coverage` endpoint recalculates the windows from the **polllog** — the file
  that records *when we were polling*, 31 kB a day compressed — so the lane can be current
  without recompiling anything. Refreshed every five minutes; the recorder writes every
  60 s, so the lane needs no more precision than that.
- ▸ **It also revealed the build had been truncating a window.** The manifest's last
  window ended at 2026-11-11 08:21Z, the build's own clock. The store says that window
  actually ran to **14:56Z** — the build cut it mid-window because that was simply when it
  stopped looking. Lane went from **7 windows and 21.4 h recorded** to **9 windows and
  33.5 h**.

**Changed**
- **Windows the build has not compiled are drawn hollow**, and the notice says why: we know
  we were listening and the raw AIS is on disk, but the vessels and alerts for that stretch
  do not exist until the next build. Drawing them solid would promise something that
  disappears when you move the cursor onto them.
- This is the honest division of what can and cannot be made live. **Coverage is an
  observation** — we either were polling or we were not, and the polllog settles it without
  any processing. **Vessels and alerts are a conclusion**, produced by the indicator
  pipeline over the whole recording, so they stay build-bound. The lane now shows exactly
  how much a rebuild would add, instead of hiding it behind a flat right edge.

**Added (tests)**
- The lane must not read its windows from the manifest, must mark post-build windows, and
  the server must expose `/coverage`.

---

## 2026-11-13 (h)

**Added**
- ▸ **A stale-build warning, because the symptom reads as data loss.** The coverage lane
  stops short of the right edge when the build falls behind the recorder, which looks
  exactly like "recent data is missing". Checked against the store: **nothing was lost** —
  790,675 records held, of which **115,617 were recorded after the build** (57,317 on 11-12,
  58,300 on 11-13). The build was **42 hours old**; its data ends at 2026-11-11 08:19Z.
- The header now shows the build's **age**, not just its date, in amber past 6 hours, and
  the time panel carries a line directly under the lane — where the symptom is seen —
  saying how far behind the build is, that the recorder kept running, that nothing is lost,
  and that a rebuild brings it in.
- Guarded by a check that `buildAgeH()` matches the manifest and that the warning exists.

---

## 2026-11-13 (g)

**Changed — the three directories now sit where their recoverability says they should**
- ▸ **It was backwards, and by accident.** The project lives inside Dropbox, so **1.9 GB of
  regenerable tile cache and 56 MB of build output were being synced to the cloud**, while
  the **25 MB of AIS recording — the only thing nobody can capture again — was the one
  directory outside it.** The small irreplaceable thing was unprotected; the large
  reproducible things were costing quota and bandwidth.

  | | was | now | why |
  |---|---|---|---|
  | `record` · 25 MB | `~/ais_data`, **not synced** | `~/Dropbox/.../ais_record` | irrecoverable → back it up |
  | `cache` · 1.9 GB | inside Dropbox | `~/Documents/custody/cache` | a function of an external source |
  | `data` · 56 MB | inside Dropbox | `~/Documents/custody/data` | a function of cache + code + config |

  All three moved. The recording was moved with the recorder stopped through its own
  `stop.sh` (SIGTERM, wait for the cycle to fsync, verify), checked at the destination —
  **23 files, 25,913,092 bytes, identical; every `.gz` passes a decompression test** — and
  the recorder restarted on the new root, where it resumed from the 45,502 records already
  in the day's file. About a minute of recording lost. The project tree inside Dropbox went
  from 2 GB to **1.8 MB**: source, config and docs, which is what belongs in version
  control anyway.

- ▸ **`aisctl.py` was reporting "no data in store" over 25 MB of intact recording.** The
  read-side CLI had its own default root — `./data` next to the script — so it never saw
  the move. It now asks `custody.paths` like everything else. The lesson is the one the
  config was built for: a path resolved in a second place is a path that will disagree.
- `viewer/server.py` gained a `translate_path` override so the browser's `/data/...`
  requests resolve to the configured directory wherever it is, with a containment check so
  a `..` in the URL cannot escape it. Verified: `/data/../../../etc/passwd` → 404.

**Fixed**
- ▸ **Two tests passed on an empty build.** After the move, `test_licences.py` reported
  "0 layers, 0 sources" and `smoke.js` read a `data/` that no longer existed — both exited
  green. A suite that passes because it found nothing is worse than no suite. Both now ask
  `custody.paths` where the data is and **fail if there is no manifest**.
- ▸ **The on-demand coastline drew nothing at Baltic zoom, silently.** `coastRefresh()`
  capped at 12 cells taken in *generation* order — south-west first — so at zoom 5 it
  fetched twelve squares of empty ocean and never reached the Baltic. Twelve `200 OK`
  responses, "12 squares loaded" on screen, zero lines on the map. Cells are now sorted by
  distance from the map centre before the cap.
- **And it would have choked once it did reach land.** A 4° square returns **7,667
  polylines**, nearly all rocks a couple of hundred metres across. The islet filter that
  existed at build time now also runs client-side, scaled by zoom: 8 km at overview, 0 at
  zoom 11 where the archipelago is the point.

**Added (tests)**
- The centre-out ordering and the zoom-scaled islet cut are both guarded. The first bug was
  silent in the worst way — no error, no warning, a layer reporting success — so it gets a
  check rather than a comment.

---

## 2026-11-13 (f)

**Fixed — licence**
- ▸ **HELCOM's depth contours cannot be used in a product that is sold, and they were in
  for an afternoon.** Their use constraints say, verbatim: *"the data are available for
  scientific research only [...] Any commercial use is prohibited."* They come from the
  Baltic Sea Bathymetry Database, which carries its own restrictions. Removed.
- **Isobaths are derived from the EMODnet DTM again** — CC BY 4.0, commercial use
  permitted with attribution. `bathymetry.contours()` had to be un-deleted. EMODnet
  publishes contours too, but they start at **50 m**, and **20 m** is the level that
  decides whether an anchor reaches the bed, which is the question the whole product
  answers. Deleting that derivation was right for the coastline and wrong for the contours.
- ▸ **Licences vary per dataset on the same server, which is the trap.** HELCOM's
  coastline is free with citation (HELCOM *and* OpenStreetMap); its subbasins are free
  with citation; its depth contours are research-only. Checked individually, and now
  recorded.

**Added — the systemic fix**
- **`config/licences.toml`**: one entry per source that enters the product, with the
  licence, whether commercial use is permitted, the required attribution, and the verbatim
  quote where it matters. 15 sources, 2 flagged as **not usable**.
- **`tests/test_licences.py`** fails the build if a layer in the manifest cites a source
  that is absent from the register, or marked non-commercial, or missing attribution. The
  failure was not one of judgement, it was one of process: there was nowhere for the
  licence to live, so nobody could notice it was unchecked.
- ▸ **Its first run found a second gap**: the vessel dossier declared no source. It pulls
  from OFAC SDN, EU FSF, Wikidata and Wikimedia Commons. **Commons is a container, not a
  licence** — each photo carries its own terms and most require naming the author, so a
  blanket "Wikimedia Commons" credit does not discharge it.

**Changed — project structure**
- **`config/custody.toml`**: AOI, paths, cache TTLs and build parameters, overridable per
  value with `CUSTODY_<SECTION>_<KEY>`. **`custody/paths.py`** is the only module that
  resolves a path; `build.py`, `custody/net.py` and `viewer/server.py` now ask it instead
  of each building its own from `__file__`.
- **`tests/`** holds `test_indicators.py` (was loose at the project root), `smoke.js` (was
  inside `viewer/`) and the new licence check, with **`tests/run.sh`** running all three.
- ▸ **Running them together immediately found a test that had been failing silently.**
  `test_indicators.py` asserted the counter key `port_mask_suppressed`; it has carried an
  indicator suffix for some time and is `port_mask_suppressed_IND-03`. The code was
  correct, the test was stale, and nobody ran it because it sat at the root with no
  command to run it. That is the whole argument for the restructuring, in one case.

**Changed — no more duplicate coastline**
- The coastline was **fetched at build time into `viewer/data` and fetched again on demand
  while panning** — the same bytes, twice, in two places. The baked copy is gone. The
  browser fetches it by the square on open and the proxy caches it; the build reads the
  same network cache to construct IND-03's coastal index, so it is **one download with two
  consumers**. Cell size now scales with zoom (4° wide out, 0.5° in) so the overview does
  not become hundreds of requests.

---

## 2026-11-13 (e)

**Changed**
- ▸ **The coastline and the isobaths are HELCOM's now; our derivations are deleted.** Both
  were produced with marching squares over the EMODnet working grid — that is, at **~3 km**
  — and HELCOM publishes both, measured. `bathymetry.contours()` and
  `bathymetry.landmask_contour()` are gone; `custody/helcom.py` replaces them.

  | | before | now |
  |---|---|---|
  | coastline | derived, 0.03° ≈ 3 km, 11,417 segments | **HELCOM layer 13**, 8 m between vertices at source, 2,516 features |
  | contours | derived, 20/50/80/100 m from the same 3 km grid | **HELCOM layer 14**, from the Baltic Sea Bathymetry Database, **10/20/50/100 m** |

  The 80 m level does not exist in HELCOM's data; 10 m appears instead, which is the one
  that marks where a medium-draught hull starts having a problem.
- ▸ **IND-03's coastal suppression got better for free.** The index that stops loitering
  being flagged within 1 NM of shore is now built from HELCOM's coastline:
  **35,945 segments against 11,417**. That was the dependency that made deleting the
  derivation non-trivial, and resolving it improved the indicator rather than preserving it.
- **Both layers moved from "Produced by Custody" to "Published by others"** in the Layers
  panel, because that is now true. 8 own layers, 16 external.
- **Baked at build time, not fetched while panning.** That is the strongest form of cache:
  once compiled there is no network, which is a property this tool sells. The on-demand
  `coasthd` layer still serves the full 8 m detail when you zoom past 8.

**Fixed**
- ▸ **The HELCOM service was silently truncating.** It caps at 10,000 records and says so
  in `exceededTransferLimit`; a single 4°×2° box over the Finnish archipelago exceeds it,
  so coastline was being lost without an error. `_query()` now pages with `resultOffset`
  until the box is exhausted. The first run of this fetch warned on two boxes — that is how
  it was found.

**Measured**
- Cost is dominated by the **number of islets, not vertices**: one 4°×2° box is 7,392
  polylines / 31,198 vertices, and generalising harder barely moves the size. Filtering by
  length does: islets under 4 km dropped, which at overview scale are smaller than a pixel.
  Whole-AOI coastline **984 kB**, contours **402 kB**.

---

## 2026-11-13 (d)

**Added**
- ▸ **HELCOM's coastline, fetched by the square as you pan.** Ours is derived in the build
  from the EMODnet depth grid's land/water mask at 0.03° — **about 3 km**. HELCOM publishes
  the real thing with a **median of 8 m between vertices**, 375× finer. That derivation was
  written without checking whether anyone already published it, which is the wrong order.
- **It is fetched, not imported, and the numbers say why.** One 1°×0.5° square is **3.7 MB**
  at native detail, so the AOI would be on the order of **1.8 GB**. The ArcGIS service
  generalises server-side: the same square with `maxAllowableOffset=0.002` is **254 kB**.
  The layer requests only the visible squares, at a detail matched to the zoom.
- **Squares are snapped to a 0.5° grid, not to the viewport.** Two similar views then
  request the *identical* URL, so the proxy's disk cache hits. Measured: four squares,
  `MISS` on first visit and **four `HIT` on returning**. `/cache/geo` is a new GET endpoint
  with a 30-day TTL — a coastline does not change between sessions.
- Below zoom 8 it does not fetch at all and says so: at Baltic-wide zoom the built-in
  coastline is already finer than the screen.

**Changed**
- `maps.helcom.fi` added to the proxy allowlist.
- The built-in layer is now labelled **"Coastline (our own, from the DTM)"**, so the two
  are not mistaken for each other. Both stay, each where it wins: the derived one is
  455 kB, instant and works offline; HELCOM's is what you want once 3 km starts showing.

**Added (tests)**
- The grid snapping is guarded: two near-identical viewports must produce the same cell
  list, and the requested detail must fall with zoom. If someone swaps the grid for the
  exact bbox, every mouse drag becomes a fresh download and the cache stops meaning
  anything — that is the failure the check exists for.

**Worth knowing: this is a pattern, not a one-off**
- The same six steps — envelope query, `maxAllowableOffset`, grid-snapped URL,
  `/cache/geo`, zoom gate — work for **any vector layer on the HELCOM map server**, and
  `coasthd.js` is 120 lines of worked example. Written up as **MANUAL §17b** with four
  confirmed-queryable candidates: **Exclusive Economic Zone** and **Territorial waters**
  (the tool says *where* an alert is but never *whose waters*), **Depth contours** (HELCOM's
  own isobaths, to check ours against) and **Shipping Accidents** (history to compare our
  alerts with).
- ▸ **One of them does not fit the pattern and is the most valuable:**
  `MADS/Shipping/345` — *2024 All shiptype AIS Shipping Density* — is a **raster**, so it
  needs the image path, not `/cache/geo`. It is a baseline of where ships normally are.
  Every indicator here asks "is this behaviour odd in itself"; none can yet ask **"is this
  vessel somewhere vessels do not go"**, which is a different and often stronger question.

---

## 2026-11-13 (c)

**Changed**
- ▸ **IND-07 now classifies what made the track impossible, by evidence rather than by
  intent.** AIS carries no causation, so the indicator never claimed one — but it also
  treated every impossible jump the same, and a tugboat with a duplicated MMSI scored
  **Extreme**. Measured over the store, 23 flagged identifiers and 1,547 jumps:

  | Class | What the evidence says | MMSI | Jumps |
  |---|---|---|---|
  | **Shared identifier** | the track ping-pongs — two emitters, one MMSI | 15 | 1,537 (**99.4%**) |
  | **Malformed message** | the vessel's own SOG field saturates | 1 | 2 |
  | **Unexplained** | one clean jump on an otherwise coherent track | 7 | 8 (0.5%) |

  By volume, IND-07 was almost entirely a data-quality signal. The first two classes keep
  being emitted — knowing an MMSI is not unique changes how you read everything else from
  it — but at a quarter of the score, as context rather than as an incident. Only the third
  class is an operator's problem.
- ▸ **The round-trip ratio is the discriminator for a shared identifier.** A jump followed
  by its return within three fixes is not a teleporting vessel, it is two ships. For
  RATNIK: 1,027 of 1,033 jumps have a return. No spoofer makes a hull come back a thousand
  times.
- ▸ **`SOG = 102.2 kn` is the ITU-R M.1371 saturation marker**, not a speed: the field is
  10 bits in 0.1 kn steps, 1023 means "not available" and 1022 means "102.2 or more".
  1,456 of 508,261 fixes carry it. When a message says that about itself, the position it
  carries is not evidence of anything.
- The alert panel leads with the class, so "279 kn implied" cannot be read as an incident
  when the identifier is shared.

**Not done, and why**
- **No split into "GNSS spoofing" vs "deliberate AIS falsification".** Both produce the
  same observable — a false reported position — and AIS alone cannot separate the victim
  from the perpetrator. The discriminator is the **area effect**: a spoofer illuminates a
  region, so several hulls are displaced in the same place at the same time, while a liar
  is one hull. Tested on this store: of the 8 unexplained jumps, 4 are isolated and 4
  co-occur only with shared-identifier tracks — no clean area signature. With 7 vessels and
  8 events there is nothing to calibrate against, so the split would be a label, not a
  finding.

---

## 2026-11-13 (b)

**Changed**
- ▸ **The basins are HELCOM's now, not six rectangles I drew.** The hand-drawn boxes left
  9.4% of the sea in no basin and 2,218 cells in two, which made the focus filter a source
  of error rather than a tool. The viewer now uses **`HELCOM subbasins level 2` — the 17
  units HELCOM itself uses in its HOLAS assessments**, fetched at build time from the same
  HELCOM map server the tool already queries for munitions and marine spatial planning.
  They are grouped into the **7 major basins** of the Baltic Sea Action Plan nutrient
  ceilings (Kattegat, Danish Straits, Baltic Proper, Gulf of Riga, Gulf of Finland,
  Bothnian Sea, Bothnian Bay), because seventeen buttons is a form, not a choice. The panel
  names the level-2 units behind whichever group you pick, so the claim is checkable.
- **The Gulf of Finland now reaches the Russian end**, because HELCOM's SEA-013 does.
  Checked by point: St Petersburg, Kronstadt, Vyborg, Primorsk and Ust-Luga all classify
  as Gulf of Finland. 34 of the 42 vessels east of 29.5°E are in it.

**Added**
- **An "Inland waters and lakes" group**, explicitly not a HELCOM sub-basin and labelled
  as ours. AIS reaches us from **Lake Ladoga, the Saimaa canal and Lake Mälaren**, which
  are not the Baltic and are in no sub-basin. They used to vanish from the map the moment
  you focused anything. 51 vessels live there. **Nothing is now unclassified: 0 vessels
  fall outside every group.**
- **A 5 km coastal margin.** Simplifying the coastline from 2.9M vertices to 26k puts
  quays and archipelago channels a few metres outside their own basin — without a margin
  **20.6% of vessels went unclassified, and they were the berthed ones**. At 5 km it is
  4.0%, and what remains is genuinely inland water. The number is the error the
  simplification introduces, not a licence to stretch boundaries.
- `custody/basins.py`: fetch, iterative Douglas-Peucker (the recursive form blows the stack
  at 500k points), and dropping islet rings that cost as much per query as the coastline
  but never change which basin a point is in. 2,888,332 → 26,156 vertices, 510 kB.

**Fixed**
- ▸ **The browser was serving stale JavaScript.** Nothing told it not to cache the
  viewer's own files, so changing a `.js` and reloading could leave a mix of old and new —
  the symptom being "the bug is still there" when the fix was already deployed. The map
  key dismissal was reported as still broken for exactly this reason; it verified clean in
  a fresh session. `Cache-Control: no-cache, must-revalidate` now applies to the viewer's
  own files, and only those — tiles and satellite crops keep their long cache.

**Added (tests)**
- 17 level-2 units in 7 groups, and **zero vessels unclassified**. The inland count is
  printed rather than capped: it is a real property of the AIS feed, not a defect.

---

## 2026-11-13 (a)

**Added**
- **Time zone setting.** Every timestamp was UTC with no way to change it, which reads as
  "two hours slow" to anyone in Helsinki. UTC stays the default — it is how AIS reports,
  how Sentinel acquisitions are stamped and how an incident report is written — but
  Settings now offers this computer's offset, EET, CET and MSK. **The offset label is glued
  to every time shown** (`Z`, `+02:00`), because the failure this prevents is not reading
  the wrong clock, it is not knowing which clock you are on.
- **"N alerts are outside this basin and hidden right now"**, with a one-click way back to
  the whole Baltic. It counts only what the *basin* hides, among the items the other
  filters already let through — counting against the raw total would have said "444 hidden"
  with a screen showing nothing for an unrelated reason.
- **A `Key` button** in the top bar. Closing something with no visible way back is a trap.

**Fixed**
- ▸ **Focusing a basin was a zoom with a mask on top.** It dimmed the rest of the map but
  the alert list, the vessel list and the markers still carried the whole Baltic. Focus now
  filters: 1,090 alerts → 646 in the Gulf of Finland, 1,372 vessels → 763.
- ▸ **The basin then filtered alerts twice, by two criteria that disagree.** Once by the
  alert's own position, and again through `opsPass` → `visibleOnMap`, which had picked up
  the basin check and judges by *where the vessel is now*. An alert has its own position;
  where the hull sits today does not change where the thing happened. Split into
  `vesselPassesFilter` (no basin, used for alerts) and `visibleOnMap` (basin, used for
  drawing vessels).
- **The map key reappeared a second after you closed it.** `renderMapKey()` runs on every
  snapshot redraw — every live poll, every cursor move — and set `hidden = false` without
  asking. The dismissal is now remembered across sessions.
- **The basin boxes left real gaps.** Measured on 20,524 sea cells: 14.9% of the AOI's sea
  fell in no basin. The box that mattered was the Estonian coastal strip between 58.6°N and
  59.0°N, lost between the Gulf of Finland, the Baltic Proper and the Gulf of Riga. Boxes
  widened; vessels outside every basin went 2.8% → 1.9%, alerts 3.7% → 1.7%.

**Changed**
- **Basin counts moved out of the basin bar** to where the data lives: alerts into the
  alert panel, vessels into the Vessels tab. The bar keeps what belongs to choosing a
  basin — what is in it, and the warning that the boundaries are rectangles.
- **The cable layers are named as cables.** *Trunk corridors* → **Submarine cables and
  pipelines (trunk)**. They were always toggleable under *Subsea infrastructure*; the name
  did not say what they were.
- **The timeline footer says what its numbers are.** The two dates are now labelled
  *slider starts* / *ends* — they are the ends of the control above them, not loose dates.
  *"575 fresh of 1371 shown"* became *"575 of 1371 are current, the rest are last known"*,
  with the full explanation on hover. It is the number that stops a stale picture being
  read as a live one, so it stays.

**Verified, not fixed**
- ▸ **The six basins do not cover 100% of the Baltic, and cannot.** Six rectangles do not
  tile a sea with this shape. After widening: 9.4% of the AOI's sea is in no basin and
  2,218 cells are in two. Most of the remainder is not Baltic at all — the Norwegian
  Atlantic edge and the North Sea side, which the AOI rectangle includes. What is left is
  Lake Ladoga and the Saimaa canal: inland waters, not the Baltic. Stretching "Gulf of
  Finland" across a Russian lake to make a number read 100% would be lying with geometry.
  The honest fix is the hidden-count indicator, and smoke now caps both figures.

**Added (tests)**
- Basin coverage: fails if more than 12% of sea cells or 3% of alerts fall outside every
  basin, and prints both numbers.
- Basin focus actually filters, **and the hidden count equals exactly what the focus hid**.
  The first version of this test passed for the wrong reason: it measured across a cursor
  move made by an earlier check, so the difference it saw was the time window, not the
  basin. Turning the time filter off first is what made it find the double-filtering bug.

---

## 2026-11-11 (r)

**Fixed**
- ▸ **Two clocks were contradicting each other.** The timeline governed the map; the vessel
  panel's *Replay track* animated its own comet by interpolating a private marker and never
  touched `TIME.cursor`. Replaying a vessel's last 24 hours left the rest of the map frozen
  at a different instant. The animation now **drives the global cursor**, throttled to
  150 ms — the comet runs at 60 fps and redrawing the snapshot is ~1,300 markers, so
  pushing every frame would make the replay useless. Verified in the browser: four samples
  during a replay give four different cursor times and the whole map's scene changes with
  them.
- **The vessel range now frames the timeline.** Picking *24h* in the vessel panel said
  "last 24 hours" while the bar below still showed the full 15 days. The range is measured
  back from *that vessel's* last fix, so the bar is framed on exactly that span; closing
  the vessel restores the full range.
- **Only one playback can run.** Starting the vessel replay stops the timeline play and
  disengages live follow (otherwise the next 60 s poll would yank the cursor to the present
  mid-replay); starting the timeline play stops the vessel replay.
- ▸ **"Back to now" and "Latest" were the same button.** Line for line: `stopPlay()`, set
  `LIVE.follow = true`, `setCursor(TIME.t1, …)`. "Back to now" is gone; in its place the
  bar now says *cursor parked — Latest goes back to live*, which is the thing that was
  actually missing: **why** the cursor is not at the present.

**Added**
- A smoke check for the single clock: the vessel range frames the bar, `animateTrack`
  still pushes `setCursor`, the two playbacks exclude each other, and no second
  back-to-now button has reappeared.

**Fixed (harness)**
- `showVessel` cleared its severity class with string surgery on `className`; it now uses
  `classList`. The string form broke under the smoke DOM and would have broken on any
  element whose `className` is not a plain string.
- The `TIME.t0`/`t1` shim lived inside one check, so every check running before it measured
  against `t0 = t1 = 0`. Moved to the setup, where it runs once.

---

## 2026-11-11 (q)

**Changed**
- ▸ **Three vessel layers collapsed into one, governed by the time cursor.** They turned
  out to be the same database at three instants, which the code already admitted:
  `liveFetch()` was appending every fix into `HIST`, and `HIST` is exactly what the cursor
  snapshot reads. The live layer was the newest point of that timeline drawn a second time
  in a different colour; `positions` was another point of it — **884 of 1,207 of its
  markers sat exactly on the last fix of the vessel's own track**. There is now one vessel
  layer. *Live* is not a layer, it is the cursor parked on the newest fix while polling
  continues every 60 s; drag the cursor back and the same layer draws that instant.
- **`positions.geojson` is still loaded, just not drawn.** It carried one thing the
  timeline could not: **103 vessels heard exactly once**, which never reach two points and
  so never get a track. Those are now seeded into `HIST` as single-point tracks
  (`seedSingleFixVessels`), so nothing is lost by dropping the layer.
- The map key reports the single view and says whether the cursor is following the newest
  fix or parked. Moving it by hand disengages live without switching it off — polling
  continues, so the timeline keeps growing; **Latest** re-engages.

**Fixed**
- **Restored `LIVE.follow = false` on manual cursor moves**, lost while removing the
  multi-view code: the key claimed it was following the newest fix while sitting three
  hours in the past.

**Added**
- **A regression test for the bug that started this.** Smoke asserts that three *recorded*
  instants produce three different scenes — comparing positions, not MMSI sets, because
  the same vessels appear in all three. It samples timestamps from the densest track
  rather than percentages of the span: the store has 8 coverage windows across 15.5 days,
  and two instants inside the same gap legitimately return the identical frozen scene.
  Also asserts no second vessel layer has reappeared, and that no vessel in
  `positions.geojson` is missing from `HIST`.

---

## 2026-11-11 (p)

**Fixed**
- ▸ **Play moved the clock and nothing moved on the map.** A regression from (o): with
  Live AIS as the active view, `drawSnapshot()` returned early, so scrubbing or pressing
  Play advanced the cursor while the live markers stayed frozen at *now*. Moving the cursor
  now switches the cursor snapshot on — it is the only view that follows the timeline —
  and switches Live AIS off, because live is pinned to now and would draw every vessel
  twice, far apart. An on-map notice says what happened and that **Latest** goes back.
- **The timeline read "0 fresh of 0 shown" while the map was full of ships.** With the
  snapshot off those counts are not zero, they are *not applicable*: the active view does
  not depend on the cursor. It now says so.
- **The app booted with every vessel drawn twice.** The default view was the snapshot and
  `liveOn()` added live on top, so a fresh load started with both. Booting into live now
  sets live as the only view.

**Changed**
- **The three vessel views are no longer mutually exclusive.** Comparing where a vessel was
  at the cursor against where it was last heard is a fair question, and forcing one view
  removed the ability to ask it. Combining is allowed; what was wrong was that it happened
  silently. The map key now counts the overlap — *"878 vessels are drawn twice"* — and
  offers one click back to a single view.
- The floating Legend no longer repeats the vessel counts and no longer claims only one
  view is ever drawn, which had stopped being true. It carries the vocabulary; the map key
  carries the state.

**Added**
- **A permanent map key: "What you are looking at".** The floating legend explains the
  vocabulary; this explains what is on screen right now — which views are on, what instant
  each answers for, and live counts of **under way / stopped / no heading** for each. The
  glyphs come from the same `shipIcon()` the map uses. Pinned bottom-left so nobody has to
  find a button to learn what a triangle means.
- `#botleft` stacks the legend and the map key instead of each positioning itself, which
  is why they used to overlap.

---

## 2026-11-11 (o)

**Fixed**
- ▸ **Every vessel was drawn twice in live mode.** Three layers answer the same question —
  *where is each vessel* — at three different instants: `live` (fetched from digitraffic
  now), `snapshot` (at the time cursor, from our recording) and `positions` (last known,
  frozen at build time). `renderTimeBar()` called `drawSnapshot()` unconditionally and
  `liveOn()` calls `renderTimeBar()`, so live mode removed the snapshot and then
  immediately put it back. Both are green, so the duplicate read as clutter rather than as
  a bug. Measured: **883 of the 906 live vessels are also in Last known**, which carries
  1,275 because it keeps vessels that have since gone quiet.
- **The live layer was not in the Layers panel at all.** It is Fintraffic AIS like the
  other two, but it was governed only from the Time panel, so turning off *AIS tracks* and
  *Last position per vessel* left ships on the map with nothing to switch them off.
- **A vessel view no longer vanishes from the panel.** The three rows render from
  `VESSEL_VIEW` rather than from whether the layer object exists, so switching away from
  one does not remove the way back to it. Unchecking the active one falls back to the
  snapshot instead of leaving an empty map.
- ▸ **Smoke's map stub could not see anything.** `hasLayer()` returned false
  unconditionally and `addTo()` returned a fresh stub without telling the map, so any
  check about what is drawn passed vacuously. The stub now tracks its layers and `addTo`
  registers, as Leaflet does. The new exclusivity check is the first one that could
  actually fail.

**Added**
- **`VESSEL_VIEW`, one owner for the three.** Exactly one is drawn; all three checkboxes
  go through `setVesselView()`. Smoke fails if two are on the map at once, or if
  `drawSnapshot` re-adds the snapshot while live is the active view.
- **A legend for the vessel glyphs**, which carried two dimensions of meaning explained
  nowhere: **shape** says whether the vessel broadcast a bow heading (arrow, rotated to it)
  or did not (circle — 12.6% of fixes), and **colour** says which layer and therefore which
  instant. Dim and small means stopped, or stale at the cursor. The legend glyphs are
  generated by the same `shipIcon()` the map uses, so legend and map cannot drift apart.
- **A line under each of the three rows** saying what instant it answers for, and a note
  saying why only one can be on.

**Changed**
- **The live layer is cyan, not green.** It and the snapshot were `#6ff0a0` and `#58d68d`
  — two greens close enough to be the same colour, which is exactly the pair the
  duplicate-draw bug produced. Colour is the only thing distinguishing which instant a
  marker belongs to, so the two have to be told apart.

---

## 2026-11-11 (n)

**Changed**
- **Layers are now split by origin before subject.** Two blocks: *Produced by Custody* —
  thresholds we chose, geometry we computed, judgements we made — and *Published by others,
  drawn as published*. The question that decides the block is one: did this tool decide it,
  or is it someone else's data drawn unaltered? Mixing them left the reader unable to tell
  what they can cite to a third party from what is our own call. `tracks` and `positions`
  sit under external on purpose although we assemble them: what is drawn are Fintraffic AIS
  broadcasts, not a conclusion. `coastline` and `isobaths` sit under ours for the opposite
  reason — that geometry is computed from the DTM, it is not an EMODnet product.
- **ESA CDSE catalogue is off by default**, with a line under it saying what it is. It is
  twelve rectangles covering half the Baltic that answer no operational question: it is
  provenance, not observation.
- ▸ **Why every CDSE footprint reads 0 AIS.** It is the finding, not a fault: the twelve
  scenes span 4.8–22.8°E while our AIS coverage runs 15.5–30.5°E, and **10 of the 12 do
  not overlap a single cell where our receivers have ever heard a message**. At the
  acquisition hour the store held 10 positions in the whole AOI. The layer note now says
  this instead of leaving a column of zeros unexplained.

**Fixed**
- **Layer counts counted map labels as data.** `renderLayerRows` counted Leaflet children,
  and layers that add a per-feature label counted double — the CDSE catalogue read **(24)
  for 12 scenes**. It now counts features.
- ▸ **The Spanish dictionary carried two English blocks pasted by mistake**, shadowed by
  the real translations further down, so the UI was correct but editing the first copy
  would have had no effect. Removed. The parity check could not see them: it compares key
  *sets*, and a duplicate key leaves the set unchanged.
- **Three i18n checks that the old one could not make.** Smoke now also rejects duplicate
  keys inside a dictionary and flags entries whose Spanish is byte-identical to the
  English (4 remain, all legitimately: proper nouns, "fixes", "cable").
- **A new layer can no longer land in neither block.** Smoke fails if any layer is missing
  from the origin groups or appears in both. Currently 11 ours, 14 external.

---

## 2026-11-11 (m)

**Added**
- **The vessel panel now knows which alert opened it.** Clicking through from a red
  *Extreme* alert used to land on a neutral card that never mentioned the alert, and the
  evidence for it sat below the dossier, the declared route and the satellite chip. The
  panel now carries the alert's **severity colour** (ISO 22324 / CAP, the same scale as the
  alert list) on its header, and a **Why this alert fired** block sits directly under the
  range selector.
- **That block is numbers, not prose.** New `viewer/alertgist.js` reads the `evidence`
  object the detector already emitted and states the case for *this* alert: silent for
  41 min and back at 20:05Z; 10.2° off its heading, same side in 93% of 14 fixes; 279 kn
  implied against 11.1 kn reported. One renderer per indicator, all seven covered, with a
  smoke check that walks a real alert of each type and fails on a missing or `null` field.
- **The evidence section is promoted and the exact row marked.** A gap alert puts
  *Reporting gaps* right below, with the one gap that fired it highlighted among the other
  ten. Position-based indicators get a **Positions during the alert** block holding only
  the fixes in the window — promoting the full 1,202-row list would have been a wall, not
  an answer — and the full list stays collapsed where it was.
- **The alert is drawn on the track**: the window as a thick segment in the severity
  colour over the pink trace, plus a ring at the alert's own position. *Back to the alert*
  returns to the detail view.

---

## 2026-11-11 (l)

**Fixed**
- ▸ **The depth raster was drawn in the wrong place.** Leaflet stretches an image overlay
  linearly across the *projected* rectangle, and the map is Web Mercator; the rows were
  spaced evenly in **latitude**. Between 53.5°N and 66°N that is up to **66 km of error in
  the middle of the image and zero at the top and bottom edges** — which from outside looks
  exactly like "the layer is stretched and does not line up with the others". The build now
  writes the PNG already projected to EPSG:3857, with rows spaced in Mercator y.
- **A regression check that cannot pass by accident.** `depthmap.verify()` decodes the
  published PNG and compares it cell by cell against `depth_grid.json`, built by a
  different path, counting only points whose 3x3 grid neighbourhood is uniform (within
  3 km of the coast the two sources may legitimately disagree). It scores the correct
  mapping **and** the broken one, and smoke fails unless the correct one clears 99% *and*
  beats the broken one by a clear margin. Measured: **99.59% vs 92.41%** over 5,337 samples.

**Changed**
- **The image is read from the native rasters, not from the working grid.** It was drawn
  from the 0.03° (~3 km) grid and looked it. EMODnet's **~116 m** GeoTIFF blocks are
  already in the network cache, because `fetch_grid` downloads them to build that grid, so
  reading them costs no extra network — 3.5 s of CPU. Published image went from
  718x418 to **4096x4793, ~292 m/px, 745 kB**. Band shares moved by under 1.3 points,
  which is the evidence that the quantile cuts describe the sea and not the sampling.
- `bathymetry.block_urls()` is now shared by `fetch_grid` and `depthmap`. Built separately,
  a one-decimal difference in the WCS subset would split the cache and re-download a
  gigabyte.
- **Dropped the in-browser canvas fallback.** It reimplemented the reprojection in JS, so
  there were two places to get the same thing wrong. If the PNG is missing the layer now
  says so instead of drawing something subtly wrong.

---

## 2026-11-11 (k)

**Added**
- **Baltic depth map, with a palette cut to this sea.** EMODnet's official ramp spans
  6,000 m, and the service ignores `COLORSCALERANGE`, so it cannot be rescaled from
  outside: the entire Baltic lands in one end of it and half the spectrum is spent on
  trenches that do not exist here. New layer repaints the same DTM with nine bands chosen
  by quantiles of our own grid. Land carries no value in the grid, so it stays
  transparent — only the sea is painted. The violet end now means the Baltic deeps.
  New `custody/depthmap.py`, viewer layer in `viewer/depthmap.js`.
- ▸ **The numbers that set the bands**, measured over 20,524 water cells: median depth
  **48 m**, p75 **89 m**, and **85% of the Baltic is shallower than 120 m**. Each of the
  nine bands now carries between 2.9% and 18.8% of the sea, so no colour is wasted and
  none swamps the map. One cut is not statistical: **100 m**, where anchoring a merchant
  stops being practical — the question the whole tool exists to answer. It is marked on
  the legend.

**Changed**
- **The image ships from the build, not from the browser.** `depth_grid.json` is
  subsampled to 0.06° because it is parsed at startup; a PNG is not fetched until the
  layer is switched on, so that limit does not apply to it. The build now emits
  `depth_map.png` at the **native 0.03°** — 718x418, **19 kB**, indexed PNG of nine flat
  colours, which is smaller than the subsampled JSON and four times the detail. The
  in-browser canvas renderer stays as the fallback for builds made before this change.
- **Hard edges, not interpolation.** The raster is drawn `image-rendering: pixelated`.
  With nine discrete bands, browser smoothing invents colours that are not in the legend.

**Fixed**
- **The depth legends stayed in the previous language.** `applyI18n()` only rewrites
  elements carrying `data-i18n`; both depth legends are built with `innerHTML` and `t()`,
  so switching language left them untranslated. `setLang()` now repaints them. The
  pre-existing EMODnet legend had the same bug.
- **The palette existed twice and could drift.** It is written in `depthmap.py` (which
  paints the PNG) and in `depthmap.js` (which paints the legend and the fallback). A
  smoke check now parses both and fails if the cuts or the RGB values disagree — a silent
  drift would mean the legend lying about the image.

---

## 2026-11-11 (j)

**Changed**
- **One button per action, named the same everywhere.** The vessel popups carried
  *Vessel situation* at the top and a second *Position history* at the bottom of a
  scrolling card — two controls for the same destination, the lower one worse. The trailing
  button is gone wherever the card already opens with *Vessel situation*, and the remaining
  entry points (fleet-track popup, alert detail) now use that same label instead of
  *Position history*. The collapsible *Position history* section inside the vessel panel
  keeps its name: it is a section, not a way in.

---

## 2026-11-11 (i)

**Fixed**
- **Reviewing an alert had no visible effect.** `onAlertInspected` wrote the mark to
  localStorage but never updated the in-memory `SEEN`, which is what `isSeen()` reads — so
  opening an alert did not dim it, did not move it down the list and did not move the
  counter until the page was reloaded. The whole reviewed/unreviewed feature was inert.
- **The review controls vanished when you used them.** *Only unreviewed* and *Mark all
  unread* only rendered when something was already reviewed, so pressing *Mark all unread*
  removed the buttons that had just been pressed. They are now always present and go
  disabled with a tooltip instead of disappearing. Pressing it also releases the
  *Only unreviewed* filter, so the buttons and the list cannot contradict each other.
- **The ESA CDSE footprints were invisible.** They were drawn in faint grey at weight 1,
  which worked over a dark sea and disappeared the moment the SAR mosaic put grey
  underneath. Now amber and dashed, thicker when the scene has an AIS match, each labelled
  on the map with its acquisition time and AIS count — so the layer reads without clicking.

**Added**
- **The EMODnet bathymetry WMS now carries its depth scale**, fetched from the service's
  own `GetLegendGraphic` rather than redrawn here, cached through the local proxy.
  It also states what the legend reveals: **the ramp spans 6,000 m and the whole Baltic is
  shallower than 460 m**, so the entire sea lands in the red-to-green end. The palette is
  calibrated for open ocean. The panel points to the Isobaths layer instead, cut at 20, 50,
  80 and 100 m — the range that decides whether an anchor reaches the bed. `COLORSCALERANGE`
  was tried and the service ignores it; the alternative default style renders the Gulf
  almost white, which is worse.
- Toggling a floating panel on now flashes it briefly. Several panels float over the map
  and pressing a toolbar button without seeing what appeared reads as nothing happening —
  especially when the panel was already open and the press closed it.

---

## 2026-11-11 (h)

**Added**
- **Basin focus.** The Baltic is split into its six sub-basins — Gulf of Finland, Åland Sea,
  Gulf of Bothnia, Baltic Proper, Danish Straits, Gulf of Riga. Picking one frames it,
  **dims everything outside it**, and counts what is inside: vessels, alerts, sanctioned
  hulls. ▸ Gulf of Finland 643 vessels / 259 alerts / **19 sanctioned**; Baltic Proper
  328 / 263 / 6; **Danish Straits 0 / 0 / 0**, which is the AIS coverage gap showing itself
  the moment you look at it. Boundaries are rectangles for framing and counting, and the
  panel says so — basin borders are conventional even in the literature.

**Changed**
- **The interface is English everywhere.** The leak was not in the UI strings, which tested
  clean, but in the **data**: every build layer note was written in Spanish and shown
  verbatim in Sources ▸ Build health, and `vayla.py` emitted a Spanish `restriction_es`
  field that surfaced in popups. Both translated; the Finnish original is kept because it
  is the legal term on the Väylävirasto file.
- **The Sentinel-1 scene layer now says what it is for.** Renamed from "Sentinel-1 GRD
  footprints" to **ESA CDSE catalogue (footprints + AIS cross-check)**, and the popup leads
  with the field that justifies the layer and was previously hidden:
  `ais_vessels_in_footprint_pm30min` — how many AIS vessels our own recording placed inside
  that footprint within ±30 min of acquisition. The popup also explains why there are two
  Sentinel-1 catalogues: this one is ESA CDSE at build time, few scenes with full
  provenance and the cross-check; the other is Planetary Computer live, many passes, whose
  job is to paint pixels rather than prove anything.
- Top-left overlays now stack in one column. Each had its own absolute `top`, so the basin
  selector growing pushed nothing and simply covered the source strip.

---

## 2026-11-11 (g)

**Fixed**
- **The SAR mosaic disabled the map's zoom-out button.** Leaflet derives the map minimum
  from its layers — `getMinZoom()` returns `this._layersMinZoom` unless the map sets its
  own — so declaring `minZoom: 8` on the mosaic layer, because the tiler has no tiles below
  that, silently locked navigation for the whole application. **A data-availability limit
  must never become a navigation limit.** The map now pins `minZoom`/`maxZoom` explicitly,
  which closes the door on any future layer doing the same. Verified: zoom reaches 3 with
  the mosaic loaded.
- Zooming out no longer blanks the imagery. `minNativeZoom` replaces `minZoom`, so Leaflet
  reuses the zoom-8 tiles scaled down instead of requesting tiles that do not exist.
  Measured tiles in the DOM: z9 16, z8 20, z7 49, z6 169. Below zoom 6 the layer is
  released — a cost decision, stated as such — and the panel says navigation is never
  restricted.

**Changed**
- **Progress button and panel removed.** Cosmetic badges earned a slot in the toolbar and
  gave the operator nothing.

---

## 2026-11-11 (f)

**Changed**
- **Coverage mode now uses a server-side mosaic instead of stitching scenes in the
  browser.** Registering a STAC search against Planetary Computer's `titiler-pgstac`
  returns one tile endpoint that composites on the server, with `sortby: datetime desc` so
  the most recent pass wins where swaths overlap.
  ▸ **165 tile layers → 1.** Measured on a Gulf view: 1 Leaflet layer, 1 DOM layer, 20 tile
  requests, 641 kB for the whole viewport. The patchwork seams and the stacked-opacity
  artefacts are gone because no stitching happens client-side any more.
- **The two imagery modes are now genuinely different mechanisms**, which they always
  should have been: *coverage* (Follow off) answers "how does the sea look now, everywhere"
  and is a mosaic; *reconstruction* (Follow on) answers "what did the satellite see at this
  instant" and must stay a single named scene — a mosaic there would blend dates and lie
  about the moment.
- **Below zoom 8 no radar is drawn, and the panel says why.** `titiler-pgstac` returns
  empty tiles below that (verified: z5–z7 return 0 bytes, z8 returns 30 kB) because it will
  not scan thousands of assets at once. At Baltic scale a 10 m pixel downsampled to 1 km is
  noise anyway, so the honest thing is to say so rather than fake it.

**Note on what remains**
- Brightness still steps between adjacent orbits. That is a real radiometric difference
  between passes of different dates and incidence angles, not a rendering artefact, and
  fixing it needs radiometric normalisation the free tiler does not offer.

---

## 2026-11-11 (e)

**Changed**
- **Sentinel-1 and Sentinel-2 now fill the whole visible map** when *Follow the time
  cursor* is off. Measured on a Baltic-wide view, radar coverage went **79% → 97%**, from
  10 scenes to 165. Three causes, all fixed: the catalogue limit was 40 (then 250) and only
  spanned 3 days — raised to 1000, which is ~25 days; scenes were matched by their
  rectangular bbox instead of the real swath footprint; and the selection grid had ~90 km
  cells, so any gap smaller than that went undetected — now ~45 km.
- **Scene stacking is explicit by date.** `bringToBack` put the *last* layer added at the
  very back, the opposite of what was wanted, and tilejson resolves asynchronously so
  arrival order was not chronological. Now z-index by acquisition time: where passes
  overlap, the most recent is the one you see. Optical sits below radar.
- **Timebar**: added a **1h** window — the one that shows the situation now; removed the
  duplicate LIVE badge (the button already says it); removed *Hide snapshot*, which hid
  the vessels without explaining why; and the transport controls now carry words —
  *← Prev*, *▶ Play*, *Next →* — with tooltips saying what they step through.
- The **"satellite overhead, nothing seen" popup now shows the crop too**. It is the case
  that needs the image most: only by looking can anyone say whether the detector missed
  something or there was genuinely nothing there. The AIS position is drawn as a larger
  dashed ring when it stands alone.

---

## 2026-11-11 (d)

**Added**
- **IND-07, impossible position jump.** Two consecutive fixes implying a speed no hull in
  this traffic can reach. ▸ Measured: **1,779 jumps across 28 MMSI of 1,253 tracks; worst
  case 10,420 kn — 160 km in 30 s** (VOLGOTRANS 2701, a tanker). Ten of the 28 are
  Russian-flagged, most of the rest fly flags of convenience, and **one is on the OFAC
  list**. Reported as **one alert per vessel**, not per jump: a shared MMSI produced 979
  jumps on a single tug and emitting them all would drown the list without adding anything.
  The indicator states the detection is arithmetic and the **cause is not determined** —
  MMSI collision, spoofing, decoding error or receiver fault are all consistent with it.
- **"What crossing sources produced here"** block at the top of every alert that has one.
  Each line names the two independent sources behind it — AIS × OpenStreetMap, AIS ×
  EMODnet Bathymetry, AIS × OFAC, AIS × Väylävirasto, AIS × Global Fishing Watch. It only
  appears where two genuinely different sources meet, so the tool never claims fusion it
  did not do.
- **Permanent alert bar** above the list: time window (1h/6h/24h/7d/all) and a switch to
  show or hide alerts on the map. It used to be buried in the Filters tab.
- **Reviewed vs unreviewed alerts.** Opened ones fade and carry a tick, new ones carry a
  dot and sort first. Plus *Only unreviewed* and *Mark all unread*.

**Fixed**
- Map labels were semi-transparent and illegible over SAR imagery or the OSM basemap, and
  stacked on top of each other when two events shared a spot. Now opaque with a hard
  shadow, z-ordered by importance, and offset vertically when they collide.

---

## 2026-11-11 (c)

**Added**
- The **radar confirmation popup now shows the Sentinel-1 crop itself**, with a cyan box
  on the detected target and an amber ring on the AIS position, so the offset can be judged
  by eye and a false positive can be called by eye. Scale bar included.
- **Provenance, line by line**, inside that popup: what is measured (Fintraffic AIS,
  CC BY 4.0), what is derived (the AIS position is interpolated to the acquisition
  instant), what is imagery (Copernicus Sentinel-1 GRD via Planetary Computer, scene id
  shown) and what this tool computes. The detector is named with its reference —
  two-parameter CFAR, per **D. J. Crisp, DSTO-RR-0272, 2004**, which is the citation ESA's
  own `AdaptiveThresholdingOp.java` in s1tbx gives for the same method. It also states
  plainly that the word *confirmed* is this tool's inference and nobody's published finding.
- **Operator verdict** on each detection — ship / false positive / cannot tell — stored in
  the browser and **exportable as JSON**. Used daily this becomes the labelled set the
  uncalibrated thresholds need and that does not exist today.

**Changed**
- The viewer **starts in live mode**: what is happening now, not how the world looked when
  the build ran. The time panel was already on by default.
- **Tour and What's new removed**, at the user's request, with their buttons, panels,
  strings and styles.

**Fixed**
- The viewer had **the Gulf AOI hardcoded**, so live mode filtered to the Gulf even on a
  Baltic build. ▸ Vessels on screen went from 543 to **1,043** — the 97% figure the scope
  analysis predicted. Same class of bug as the hardcoded Overpass bbox, at the other end of
  the pipeline. The AOI now comes from the manifest and the smoke test checks it.

---

## 2026-11-11 (b)

**Fixed**
- **The satellite chip panel vanished when you switched to Sentinel-2.** Switching sensor
  did not reset the "no usable imagery" flag from the previous one, so the panel collapsed
  even when a Sentinel-2 pass was available. Worse, the collapsed form had no background or
  border and was 46 px tall: from the reader's side it simply evaporated.

**Changed**
- The chip now **always shows a title bar with a show/hide toggle**, open or closed, with
  the reason written on it when there is nothing to display. State is remembered. Measured:
  the empty state went from 46 px of invisible line to ~190 px of labelled panel.
- Switching sensor or crop size resets the empty-image state, which is the whole point of
  pressing those buttons.

---

## 2026-11-11 (a) — scope: Gulf of Finland → whole Baltic

Decision and measurements: `canal/iteracion_02/14_alcance_baltico.md`.

**Changed**
- **AOI is now the whole Baltic** (9–30.5 E, 53.5–66 N). `--aoi gulf|north-baltic|baltic`
  or an explicit box; `gulf` kept because a Gulf build takes a minute and a Baltic one
  does not. ▸ AIS goes from 592 to **1,250 tracks / 438,802 fixes**: the feed was already
  delivering them and the old box threw half away.
- Bathymetry grid step now scales with AOI area, and the viewer's depth grid with it —
  the Baltic at the old 0.01° would be 2.7 M cells and megabytes blocking first paint.

**Added**
- `custody/authorities.py` — registry of who forbids what, per riparian state. One row per
  authority, so adding Sweden the day they publish an endpoint is a row, not a rewrite.
  ▸ **5 of 9 Baltic states have a restriction layer: FI, EE, DE, LT, LV. Missing: SE, PL,
  DK, RU**, each listed with the reason. Sweden is the important gap and is stated as such.
- HELCOM **MSP Restricted Use** (pan-Baltic maritime spatial plans) as the non-Finnish
  equivalent of Väylävirasto. Marks areas forbidding anything that touches the seabed.
- **AIS coverage layer**: cells where the recorder has actually heard AIS. ▸ Only **21% of
  the Baltic AOI**. Without it, an empty south reads as "nothing happening" rather than
  "we cannot hear it". Coverage dies around 57°N.
- Sources tab now carries **Legal cover around the Baltic**: the nine riparians, which
  have data and why the others do not.

**Fixed**
- `corridors.py` had the Gulf bbox hardcoded as a default and `build.py` never passed its
  own, so **widening the AOI did not widen the cables**. ▸ Trunk corridors go from 31 to
  **97**, named ones from 39 to 133, 7,368 km to 11,593 km. The constant now carries a
  warning saying it is a courtesy default, not the project AOI. C-Lion 1 now raises alerts;
  it was simply not in the corridor set before.
- EMODnet WFS truncates at 5,000 per request and the wreck layer hit it silently. Paginated:
  ▸ **6,085 wrecks, 42 of them submarines** instead of a round 5,000.
- `military_areas` note said "(FI/EE)" hardcoded while the layer now spans seven countries.

**Baltic-wide figures after the move**
- 1,149 tracks · 444,859 positions · 663 alerts · 435 exposures
- 256 defence areas · 97 munitions dumps · 6,085 wrecks · 58 MSP restricted areas
- ▸ **48 of 256 defence areas have a trunk cable inside. Across all 256 there is exactly
  one anchoring prohibition.** The Gulf finding was not a Finnish quirk.
- ▸ 101 alerts fall inside a declared defence area, 74 within 500 m of a known wreck.

---

## 2026-11-10

**Added**
- SAR ship detection (CA-CFAR, stdlib). ▸ 55 m from a published Skylight detection.
- Radar confirmation of a track: crops every Sentinel-1 pass where AIS says the vessel
  was, at that instant. Cyan = two independent sensors agree. Runs automatically.
- Declared-route projection from the AIS `destination` field, with bearing-vs-course
  divergence. ▸ Resolves 54% of 592 tracks; 48 hand-curated Baltic ports.
- Vessel situation in one click: full track, destination in frame, photo, radar check.
- Satellite chip on alerts and vessels: scale, north, crosshair, time offset.
- Seabed layers (EMODnet): 693 wrecks incl. 3 submarines, 24 defence areas, 3 munitions
  dumps. ▸ 6 of 24 defence areas have a trunk cable inside and **zero** anchoring bans.
- Vessel dossier: dimensions from AIS message 5, OFAC/EU sanctions, Wikidata photo.
  ▸ 30 hulls in the Gulf are sanctioned, 26 under RUSSIA-EO14024.
- Global Fishing Watch events and 4wings grids (needs a token).
- Disk tile cache, multi-threaded server. ▸ 1558 ms → 139 ms.
- Editor-style shell: icon rail, `Ctrl+B`, resizable panel.
- Vessels facets filter the **map**, not just the list, with a permanent banner when
  anything is hidden, and fleet tracks for the whole selection.
- What's new tour (`whatsnew.js`): every step navigates to the feature it describes.

**Changed**
- Status tab removed; health and licences to Sources, thresholds to Filters.
- Alert panel: actions first, explanation collapsed.
- Layers grouped by provenance with the source named.
- Chip and radar-confirmation blocks collapse when there is nothing to show. The chip now
  probes the loaded image: a scene can cover a point by geometry and still have no pixels
  there (swath edge, acquisition gap). It steps to the next pass, then collapses, and it
  collapses together with the confirmation block rather than alone.
- Docs consolidated into one `investigacion_preliminar/`.

**Fixed**
- Pass catalogue queried a permuted bbox — timeline lanes were showing passes over the
  **Arabian Sea**. Guard added: the bbox must contain the vessels we track.
- Passes filtered by bbox instead of true footprint, so crops came back black.
- Progress bar stuck: Leaflet has three tile endings (`load`/`error`/`abort`), two counted.
- `snapshotAt` returned zero vessels — `buildHistory` wrote `t`, the reader read `at`.
- `--left-edge` declared on `:root`, so collapsing the panel never widened the map.
- MID table covered only the Baltic; the full ITU list now lives in Python.

**Data**
- Digitraffic has no historical AIS. Port calls do go back to 2020.
- Sentinel-1 covers all three cable incidents but **no pass on 25 Dec 2024**, the Eagle S.
- Skylight is free but its EULA forbids building a competing product.
- No open database of submarine positions exists, or will.
