#!/usr/bin/env python3
"""Construye todas las capas del visor de custodia. Solo stdlib.

    python3 build.py                 # usa caché de red si existe
    python3 build.py --refresh       # vuelve a pedirlo todo
    python3 build.py --skip-net      # solo AIS + lo que haya en caché

Salida: paths.data()/*.geojson + manifest.json (ver config/custody.toml)
El manifest declara, capa a capa, si tiene datos y POR QUÉ no los tiene.
Ninguna capa se rellena con datos sintéticos: si no hay dato, va vacía y
etiquetada.
"""
import argparse
import datetime as dt
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from custody import (ais, aishub, authorities, basins, bathymetry,  # noqa: E402
                     corridors, depthmap, geo, gfw, helcom, indicators,
                     emodnet, gnssfi, gpsjam, marine, paths, seabed, sentinel,
                     vayla, vesselinfo)

HERE = os.path.dirname(os.path.abspath(__file__))
# Rutas desde config/custody.toml. Ver custody/paths.py para las tres
# categorias de almacenamiento y por que estan separadas.
OUT = paths.data()
CACHE = paths.cache()
# El almacén del grabador: la ruta la fija config/custody.toml, con respaldos.
# El 2026-11-13 se movió DENTRO de Dropbox, al revés de lo que decía el README
# de D1: la grabación es lo único del sistema que no se puede reconstruir, y
# eran ~25 MB, no los 1,9 GB de caché que sí estaban sincronizándose por error.
# Sincronizar 19 MiB/día de lo irreemplazable es exactamente lo que hay que
# sincronizar.
def resolve_ais_root(explicit=None):
    """TODOS los almacenes con grabacion, no el primero que exista.

    Devolver uno solo costo 4,6 h de observacion invisible el 2026-11-13: la
    grabadora se reinicio apuntando al respaldo y, como el principal seguia
    existiendo, nadie leyo el nuevo. Ver paths.records().
    """
    if explicit:
        if os.path.isdir(os.path.join(explicit, "raw", "locations")):
            return [os.path.abspath(explicit)]
    else:
        out = [r for r in paths.records()
               if os.path.isdir(os.path.join(r, "raw", "locations"))]
        if out:
            return out
    cands = [explicit] + paths.records() + [os.environ.get("AIS_DATA_ROOT")]
    raise SystemExit(
        "No encuentro el almacén AIS (se espera <root>/raw/locations/).\n"
        "Buscado en: %s\n"
        "Usa --ais-root PATH o exporta AIS_DATA_ROOT."
        % ", ".join(repr(c) for c in AIS_ROOT_CANDIDATES if c))
CREDS = os.path.join(HERE, "cdse_credentials.json")

# Áreas de interés. (minlon, minlat, maxlon, maxlat)
#
# `baltic` es el alcance por defecto desde el 2026-11-10. La decisión y lo
# medido están en canal/iteracion_02/14_alcance_baltico.md. Lo esencial: el
# feed de Fintraffic trae ~1.070 buques repartidos entre 15,7°E y 35,8°E, y
# el AOI del golfo sólo capturaba el 51 %. Ampliar no cuesta una fuente nueva:
# recupera dato que ya estábamos recibiendo y tirando.
#
# `gulf` se conserva porque un build del golfo tarda un minuto y uno del
# Báltico bastante más; para iterar sobre un indicador sigue siendo el útil.
AOIS = {
    "gulf":         (22.0, 59.0, 30.5, 60.9),
    "north-baltic": (16.5, 57.0, 31.0, 66.0),
    "baltic":       (9.0, 53.5, 30.5, 66.0),
}
AOI = AOIS["baltic"]
# Los niveles los fija ahora HELCOM (custody/helcom.ISOBATHS_M): publica
# -10, -20, -50, -100 y mas hondos. El 80 que se derivaba aqui no existe
# en su dato, y a cambio aparece el 10.

LICENCES = {
    "ais": "Fintraffic / digitraffic.fi, licence CC 4.0 BY",
    "osm": "(c) OpenStreetMap contributors, ODbL 1.0",
    "emodnet": "EMODnet Bathymetry Consortium - EMODnet Digital Bathymetry (DTM)",
    "copernicus": "Contains modified Copernicus Sentinel data",
    "vayla": "Väylävirasto, datos abiertos, CC BY 4.0",
    "emodnet_ha": "EMODnet Human Activities (wrecks, military areas, munitions)",
    "helcom": "HELCOM MADS — maritime spatial plans of the Baltic states",
    "gfw": "Global Fishing Watch, CC BY-SA 4.0",
    "ofac": "US Treasury OFAC SDN list, US Government work, public domain",
    "eu_sanctions": "EU consolidated financial sanctions list, European Commission",
    "wikidata": "Wikidata, CC0; images via Wikimedia Commons, per-file licence",
}

LOG = logging.getLogger("build")


def write(name, obj, manifest, layer, status, note="", **extra):
    path = os.path.join(OUT, name)
    with open(path, "w") as fh:
        json.dump(obj, fh, separators=(",", ":"))
    size = os.path.getsize(path)
    manifest["layers"][layer] = dict(
        {"file": name, "status": status, "note": note, "bytes": size}, **extra)
    LOG.info("%-14s %-9s %7d B  %s", layer, status, size, note)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="ignora la caché de red")
    ap.add_argument("--skip-net", action="store_true", help="no sale a la red")
    ap.add_argument("--ais-root", default=None,
                    help="almacén del grabador; por defecto, el declarado en "
                         "config/custody.toml (paths.record), que es también el "
                         "que usa la grabadora")
    ap.add_argument("--include-mqtt", action="store_true")
    ap.add_argument("--aoi", default="baltic",
                    help="area de interes: %s, o minlon,minlat,maxlon,maxlat"
                         % "/".join(sorted(AOIS)))
    ap.add_argument("--depth-step", type=float, default=None,
                    help="paso de la rejilla batimetrica en grados. Por defecto "
                         "se adapta al tamano del AOI: el golfo a 0,01 son "
                         "160.000 celdas, pero el Baltico entero a ese paso "
                         "serian 2,7 millones y ni el WCS ni el navegador lo "
                         "aguantan con gracia.")
    ap.add_argument("--viewer-depth-step", type=float, default=None,
                    help="paso de la rejilla de profundidad que se envia al "
                         "visor. Se carga al arrancar, asi que no puede pesar "
                         "megas: por defecto 4x el paso del build.")
    ap.add_argument("--scenes", type=int, default=12)
    ap.add_argument("--grd", action="store_true",
                    help="descarga el producto SAFE completo (~1,2 GB). Solo hace falta "
                         "para correr deteccion de buques en local: el visor ya pinta SAR "
                         "georreferenciado via Planetary Computer sin credenciales.")
    ap.add_argument("--gfw-days", type=int, default=90,
                    help="ventana hacia atras, en dias, para los eventos de Global "
                         "Fishing Watch. 0 la desactiva. Necesita GFW_TOKEN.")
    ap.add_argument("--gfw-events", default=",".join(gfw.DEFAULT_EVENTS),
                    help="tipos de evento GFW separados por coma: %s"
                         % ",".join(sorted(gfw.DATASETS)))
    ap.add_argument("--gfw-grid", default="presence",
                    help="rejilla 4wings de GFW: presence (linea base de trafico), "
                         "fishing (pesca aparente), sar (detecciones Sentinel-1), "
                         "none. Varias separadas por coma.")
    ap.add_argument("--gfw-grid-res", default="LOW", choices=["LOW", "HIGH"],
                    help="LOW = 0,1 grados; HIGH = 0,01. HIGH sobre 90 dias son "
                         "muchas celdas para el navegador.")
    ap.add_argument("--no-seabed", action="store_true",
                    help="no trae pecios, zonas militares ni vertederos de municion")
    ap.add_argument("--no-vessel-info", action="store_true",
                    help="no enriquece buques (sanciones OFAC/UE, Wikidata). Las "
                         "dimensiones desde AIS se calculan igualmente: no usan red.")
    ap.add_argument("--wikidata-limit", type=int, default=400,
                    help="cuantos IMO se consultan en Wikidata, de mayor a menor eslora")
    ap.add_argument("--depth-samples", type=int, default=120,
                    help="tope de peticiones depth_sample (procedencia)")
    args = ap.parse_args()

    global AOI
    if "," in args.aoi:
        AOI = tuple(float(x) for x in args.aoi.split(","))
        if len(AOI) != 4:
            raise SystemExit("--aoi necesita 4 numeros: minlon,minlat,maxlon,maxlat")
    elif args.aoi in AOIS:
        AOI = AOIS[args.aoi]
    else:
        raise SystemExit("--aoi desconocido: %s (hay %s)"
                         % (args.aoi, ", ".join(sorted(AOIS))))
    # El paso se escala con el area para que el numero de celdas se mantenga
    # en el mismo orden de magnitud sea cual sea el alcance.
    span = (AOI[2] - AOI[0]) * (AOI[3] - AOI[1])
    if args.depth_step is None:
        args.depth_step = 0.01 if span < 30 else (0.02 if span < 150 else 0.03)
    if args.viewer_depth_step is None:
        args.viewer_depth_step = min(0.08, max(0.05, args.depth_step * 2))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    t_build = time.time()
    args.ais_root = resolve_ais_root(args.ais_root)
    LOG.info("almacén AIS: %s", " + ".join(args.ais_root))
    # Las tres rutas, dichas al arrancar y no sólo en la configuración: cuando
    # algo se mueve de sitio, el log es el primer sitio donde se mira.
    LOG.info("escribo el build en: %s", OUT)
    LOG.info("caché de red en:     %s", CACHE)
    LOG.info("las tres salen de:   %s", os.path.join(HERE, "config", "custody.toml"))

    # Las capas que nacen dentro de un try y se consumen mas abajo arrancan
    # declaradas: si su etapa falla, el consumidor recibe None en vez de
    # reventar con NameError a mitad del build.
    res_fc = None
    trunk = []
    n_trunk = 0
    grid = None

    manifest = {"built_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "aoi": list(AOI), "licences": LICENCES, "layers": {}, "stats": {}}

    # ---------------------------------------------------------------- 1 AIS
    fixes, ais_st = ais.load_fixes(args.ais_root, bbox=AOI, include_mqtt=args.include_mqtt)
    vessels = ais.load_vessels(args.ais_root)
    polls = ais.load_polls(args.ais_root)
    coverage = ais.coverage_windows(polls)
    tracks = ais.build_tracks(fixes, min_fixes=2)
    dataset_end = max((f["ts"] for f in fixes), default=0)
    dataset_start = min((f["ts"] for f in fixes), default=0)
    ais_st.update({"tracks": len(tracks), "vessels_with_metadata": len(vessels),
                   "polls": len(polls), "coverage_windows": len(coverage),
                   "coverage_seconds": sum(b - a for a, b in coverage) / 1000.0,
                   "ais_span_utc": [
                       dt.datetime.fromtimestamp(dataset_start / 1000, dt.timezone.utc).isoformat(),
                       dt.datetime.fromtimestamp(dataset_end / 1000, dt.timezone.utc).isoformat()]})
    manifest["stats"]["ais"] = ais_st

    # Dónde llega el AIS de verdad. Con el AOI en el Báltico, media superficie
    # es agua que no vemos, y un mapa vacío se lee como «no pasa nada».
    try:
        cov_fc, cov_st = ais.coverage_cells(fixes, step=0.5)
        manifest["stats"]["ais_coverage"] = cov_st
        area_aoi = (AOI[2] - AOI[0]) * (AOI[3] - AOI[1])
        seen = cov_st["cells"] * 0.25
        cov_st["aoi_fraction_seen"] = round(seen / area_aoi, 3) if area_aoi else None
        write("ais_coverage.geojson", cov_fc, manifest, "ais_coverage",
              "ok" if cov_fc["features"] else "empty",
              note="0.5 deg cells where the recorder has actually heard AIS: %d, "
                   "which is %.0f%% of the AOI. Outside them it is not that nothing "
                   "is moving: it is that we cannot hear it."
                   % (cov_st["cells"], 100 * (cov_st["aoi_fraction_seen"] or 0)),
              cells=cov_st["cells"], aoi_fraction=cov_st["aoi_fraction_seen"])
    except Exception as exc:
        LOG.warning("cobertura AIS: %s", exc)
    manifest["time"] = {
        "coverage_windows_ms": [[int(a), int(b)] for a, b in coverage],
        "dataset_start_ms": int(dataset_start), "dataset_end_ms": int(dataset_end),
        "built_epoch_ms": int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000),
        "coverage_seconds": ais_st["coverage_seconds"],
        "poll_period_s": 60,
    }
    LOG.info("AIS: %d fixes, %d MMSI, %d trazas, %d ventanas de cobertura",
             ais_st["fixes_kept"], len(set(f["mmsi"] for f in fixes)), len(tracks),
             len(coverage))

    # Trazas: la conversion vive en ais.tracks_geojson(), compartida con el
    # motor en vivo. El visor fusiona las dos en el mismo HIST, asi que
    # partir los segmentos con dos criterios distintos haria que la misma
    # derrota cambiase de forma al cruzar la frontera del build.
    gap_ms = indicators.THRESHOLDS["max_gap_s"] * 1000
    tfc, tst = ais.tracks_geojson(tracks, vessels, gap_ms)
    feats, n_seg, n_pts = tfc["features"], tst["segments"], tst["vertices"]
    write("tracks.geojson",
          {"type": "FeatureCollection", "features": feats,
           "properties": {"attribution": LICENCES["ais"]}},
          manifest, "tracks", "ok" if feats else "empty",
          note="%d tracks, %d segments, %d positions" % (len(feats), n_seg, n_pts),
          tracks=len(feats), segments=n_seg, positions=n_pts)

    # posiciones sueltas (último fix de cada buque) para el mapa de situación
    last = [tr[-1] for tr in tracks.values()]
    write("positions.geojson",
          {"type": "FeatureCollection",
           "features": [{"type": "Feature",
                         "geometry": {"type": "Point",
                                      "coordinates": [round(f["lon"], 5), round(f["lat"], 5)]},
                         "properties": {"mmsi": f["mmsi"],
                                        "name": (vessels.get(f["mmsi"], {}) or {}).get("name"),
                                        "sog_kn": f["sog"], "cog_deg": f["cog"],
                                        "heading_deg": f["heading"],
                                        "navStat": f["navStat"],
                                        "navStat_text": ais.NAVSTAT.get(f["navStat"]),
                                        "ts_ms": f["ts"]}} for f in last],
           "properties": {"attribution": LICENCES["ais"]}},
          manifest, "positions", "ok" if last else "empty",
          note="last known fix per vessel", count=len(last))

    # -------------------------------------------------------- 2 corredores
    corr_fc, corr_st, port_fc = None, {}, None
    port_mask = geo.PolygonMask()
    try:
        corr_fc, corr_st = corridors.fetch_corridors(
            bbox=(AOI[1], AOI[0], AOI[3], AOI[2]),
            refresh=args.refresh and not args.skip_net)
        manifest["stats"]["corridors"] = corr_st
        # Dos ficheros: los 31 trunk se pintan siempre; los ~5.600 ramales
        # portuarios sin nombre son 2,4 MB y saturan el render, van aparte y
        # apagados por defecto.
        # Overpass devuelve la geometría COMPLETA de cada vía, no la recortada
        # al bbox: Nord Stream y Fenno-Skan llegan hasta Alemania y Suecia y
        # descuadran el encuadre del visor. Se recortan al AOI, interpolando el
        # punto de cruce.
        def clip_feats(feats):
            out = []
            for f in feats:
                parts = geo.clip_polyline(f["geometry"]["coordinates"], AOI)
                if not parts:
                    continue
                g = ({"type": "LineString", "coordinates": [list(c) for c in parts[0]]}
                     if len(parts) == 1 else
                     {"type": "MultiLineString",
                      "coordinates": [[list(c) for c in p] for p in parts]})
                props = dict(f["properties"])
                props["length_m_in_aoi"] = round(
                    sum(geo.polyline_length_m(p) for p in parts), 1)
                out.append(dict(f, geometry=g, properties=props))
            return out

        trunk = clip_feats([f for f in corr_fc["features"] if f["properties"]["trunk"]])
        other = clip_feats([f for f in corr_fc["features"] if not f["properties"]["trunk"]])
        corr_st["trunk_km_in_aoi"] = round(
            sum(f["properties"]["length_m_in_aoi"] for f in trunk) / 1000.0, 1)
        write("corridors_trunk.geojson",
              dict(corr_fc, features=trunk), manifest, "corridors", "ok",
              note="%d OSM elements in the AOI, %d named, %d trunk "
                   "(named and >=5 km) = %.0f km total, %.0f km inside the AOI. "
                   "OSM snapshot %s"
                   % (corr_st["elements"], corr_st["named"], corr_st["trunk"],
                      corr_st["trunk_km"], corr_st["trunk_km_in_aoi"],
                      corr_st["osm_timestamp"]),
              elements=corr_st["elements"], trunk=corr_st["trunk"],
              trunk_names=corr_st["trunk_names"],
              osm_timestamp=corr_st["osm_timestamp"])
        write("corridors_other.geojson",
              dict(corr_fc, features=other), manifest, "corridors_other", "ok",
              note="%d unnamed or <5 km subsea elements (harbour spurs, "
                   "service drops). Layer off by default" % len(other),
              elements=len(other))
    except Exception as exc:
        LOG.error("corredores: %s", exc)
        write("corridors_trunk.geojson", {"type": "FeatureCollection", "features": []},
              manifest, "corridors", "no data", note="Overpass failed: %s" % exc)
        write("corridors_other.geojson", {"type": "FeatureCollection", "features": []},
              manifest, "corridors_other", "no data", note="Overpass failed: %s" % exc)

    try:
        port_mask, port_fc, port_st = corridors.fetch_port_mask(
            bbox=(AOI[1], AOI[0], AOI[3], AOI[2]),
            refresh=args.refresh and not args.skip_net)
        manifest["stats"]["port_mask"] = port_st
        write("ports.geojson", port_fc, manifest, "ports", "ok",
              note="%d polygons + %d nodes buffered to 1500 m" % (port_st["polygons"],
                                                                  port_st["nodes"]),
              polygons=port_st["polygons"], nodes=port_st["nodes"])
    except Exception as exc:
        LOG.error("máscara de puertos: %s", exc)
        write("ports.geojson", {"type": "FeatureCollection", "features": []},
              manifest, "ports", "no data", note="Overpass failed: %s" % exc)

    corridor_idx, n_trunk = (corridors.build_index(corr_fc) if corr_fc
                             else (geo.SegmentIndex(), 0))

    # ------------------------- 2b restricciones de navegación (Väylävirasto)
    ban_mask = geo.PolygonMask()
    try:
        if args.skip_net:
            raise RuntimeError("--skip-net")
        res_fc, res_st = vayla.fetch_restrictions(AOI, refresh=args.refresh)
        ban_mask = vayla.anchor_ban_mask(res_fc)
        near = vayla.anchor_bans_near_corridors(res_fc, corridor_idx)
        res_st["anchor_ban_vs_trunk"] = near
        manifest["stats"]["restrictions"] = res_st
        write("restrictions.geojson", res_fc, manifest, "restrictions", "ok",
              note="%d Vaylavirasto navigation restrictions in the AOI, of which %d are "
                   "anchoring prohibitions (Ankkurin kayttokielto); %d within 2 km of "
                   "a trunk corridor"
                   % (len(res_fc["features"]), res_st["anchor_ban"],
                      near["within_2000m_of_trunk"]),
              areas=len(res_fc["features"]), anchoring_prohibited=res_st["anchor_ban"],
              anchor_ban_within_2km_of_trunk=near["within_2000m_of_trunk"],
              by_type=res_st["by_type"])
    except Exception as exc:
        LOG.error("restricciones Väylä: %s", exc)
        write("restrictions.geojson", {"type": "FeatureCollection", "features": []},
              manifest, "restrictions", "no data", note="Vaylavirasto WFS: %s" % exc)

    # ------------------------------------- 2b forzamiento y cobertura ajena
    # Copernicus Marine: corriente, ola y hielo. Es lo que separa DERIVA de
    # MANIOBRA en IND-02, y la corriente no la da ninguna otra fuente abierta.
    try:
        cat, m_st = marine.catalogue(refresh=args.refresh and not args.skip_net)
        write("marine_layers.json", cat, manifest, "marine", "ok",
              note="%d Copernicus Marine WMTS layers across %d Baltic products "
                   "(currents, waves, ice, reanalysis). The WMTS needs no "
                   "credentials; the raw data through OPeNDAP does. Surface "
                   "current direction carries %d deg RMS error, so it supports "
                   "'there was a current', not a computed drift"
                   % (m_st["layers"], m_st["products"],
                      marine.CURRENT_DIR_RMS_DEG),
              layers=m_st["layers"])
    except Exception as exc:
        LOG.warning("marine: %s", exc)
        write("marine_layers.json", {"layers": []}, manifest, "marine",
              "no data", note="Copernicus Marine WMTS: %s" % exc)

    # EMODnet Human Activities: la linea base de trafico de TODO el AOI.
    # Nuestra grabacion cubre el 21 %; esto dice por donde se pasa en el 100 %,
    # construido con AIS que no tenemos. No sirve para el ahora --- es mensual
    # y agregado--- sino para saber que es normal antes de llamar raro a algo.
    try:
        ecat, e_st = emodnet.catalogue(refresh=args.refresh and not args.skip_net)
        write("emodnet_layers.json", ecat, manifest, "emodnet", "ok",
              note="%d EMODnet Human Activities WMS layers: EMSA route density "
                   "(monthly, 1 km, to last month), Cogea vessel density "
                   "(monthly by ship type, 2017-2024) and the official EU "
                   "aggregation of cables, pipelines and wind farms. Baseline "
                   "for the whole AOI, including the 79%% our own receivers "
                   "cannot hear" % e_st["layers"],
              layers=e_st["layers"])
    except Exception as exc:
        LOG.warning("emodnet: %s", exc)
        write("emodnet_layers.json", {"layers": []}, manifest, "emodnet",
              "no data", note="EMODnet Human Activities WMS: %s" % exc)

    # INTERFERENCIA DE LA NAVEGACION POR SATELITE.
    #
    # Traficom lo dice sin rodeos: el problema esta en el Golfo de Finlandia, y
    # un buque cuyo GPS miente produce exactamente la imagen que marca IND-07,
    # el salto de posicion. Sin esta capa ese indicador no puede separar un
    # transpondedor manipulado de un receptor interferido.
    #
    # Dos fuentes que miden cosas distintas y se complementan:
    #   estaciones fijas  nivel del mar, cada 30 s, AHORA, solo Finlandia
    #   aeronaves         10 km de altura, agregado 24 h, 1-2 dias tarde,
    #                     pero cubre todo el Baltico donde haya vuelos
    try:
        gfc, g_st = gnssfi.snapshot(aoi=AOI)
        write("gnss_stations.geojson", gfc, manifest, "gnss_stations", "ok",
              note="%d of 47 FinnRef reference stations inside the area, "
                   "carrier-to-noise quality per constellation. Fixed ground "
                   "receivers at sea level, stored every %s s with a 15 degree "
                   "elevation mask -- the only source here that measures NOW. "
                   "It measures signal degradation, not its cause, and it "
                   "measures it on land, not at sea"
                   % (g_st["stations"], g_st.get("obs_interval_s")),
              stations=g_st["stations"])
    except Exception as exc:
        LOG.warning("gnss-finland: %s", exc)
        write("gnss_stations.geojson", {"type": "FeatureCollection",
              "features": []}, manifest, "gnss_stations", "no data",
              note="GNSS-Finland: %s" % exc)

    try:
        # Primero el contorno de lo observado y despues los hexagonos. En ese
        # orden a proposito: si el contorno falla, se sabe antes de pintar unos
        # hexagonos que, sin el, no se pueden leer --- un hueco sin contorno
        # parece calma y es ceguera.
        cfc, c_st = gpsjam.coverage(AOI)
        manifest["stats"]["gps_interference"] = c_st
        write("gps_interference_coverage.geojson", cfc, manifest,
              "gps_interference_coverage", "ok" if cfc["features"] else "empty",
              note="Where this layer can see at all: %s km2, %.0f%% of the AOI, "
                   "in %d pieces, for %s. The remaining %.0f%% had fewer than "
                   "two aircraft all day and was not measured -- open sea and "
                   "the Gulf of Bothnia, mostly. Inside the outline a missing "
                   "hexagon means the GPS was fine; outside it means nothing "
                   "was looked at. Cells enter by their centre and are drawn "
                   "whole, so the edge overshoots by up to 11 km"
                   % (f"{c_st['area_observed_km2']:,}",
                      100 * (c_st["aoi_fraction_observed"] or 0),
                      len(cfc["features"]), c_st["day"],
                      100 * (1 - (c_st["aoi_fraction_observed"] or 0))),
              area_km2=c_st["area_observed_km2"],
              aoi_fraction=c_st["aoi_fraction_observed"],
              pieces=len(cfc["features"]), day=c_st["day"])
    except Exception as exc:
        LOG.warning("gpsjam coverage: %s", exc)
        write("gps_interference_coverage.geojson", {"type": "FeatureCollection",
              "features": []}, manifest, "gps_interference_coverage", "no data",
              note="GPSJAM coverage: %s" % exc)

    try:
        jfc, j_st = gpsjam.geojson(AOI)
        write("gps_interference.geojson", jfc, manifest, "gps_interference", "ok",
              note="%d hexagons of about 1770 km2 with at least one degraded "
                   "aircraft, out of %d in the area, for %s. Derived from the "
                   "accuracy aircraft declare over the air. AGGREGATED OVER A "
                   "WHOLE DAY and %s: five minutes of interference paints the "
                   "cell for twenty-four hours, so it answers 'there was "
                   "interference around here that day', never when. Blind "
                   "where aircraft do not fly: see gps_interference_coverage "
                   "for the outline of what was actually measured. Licence "
                   "not published by the site"
                   % (j_st["cells_with_degraded"], j_st["cells_in_aoi"],
                      j_st["day"], "1-2 days late"),
              cells=j_st["cells_with_degraded"], day=j_st["day"])
    except Exception as exc:
        LOG.warning("gpsjam: %s", exc)
        write("gps_interference.geojson", {"type": "FeatureCollection",
              "features": []}, manifest, "gps_interference", "no data",
              note="GPSJAM: %s" % exc)

    # AISHub: donde hay cobertura ajena que nosotros no tenemos. No es
    # decorado -- es el caso de negocio de pedir el acceso, dibujado.
    try:
        ah, a_st = aishub.fetch(AOI, refresh=args.refresh and not args.skip_net)
        write("aishub_stations.geojson", ah, manifest, "aishub", "ok",
              note="%d AISHub stations inside the AOI of %d in the network, "
                   "%d of them in the 56-60N 16-24E gap where our own coverage "
                   "dies -- including Visby and Faro on Gotland, where the "
                   "November 2024 cables were cut. Station list only: the "
                   "aggregated feed needs a key and may not be redistributed"
                   % (a_st["in_aoi"], a_st["network_total"], a_st["in_gap"]),
              stations=a_st["in_aoi"], in_gap=a_st["in_gap"])
    except Exception as exc:
        LOG.warning("aishub: %s", exc)

    # --------------------------------------------- 2c subcuencas HELCOM
    # La division estandar del Baltico, no seis cajas dibujadas a mano. Se
    # usa para enfocar y para clasificar cada buque y cada alerta.
    try:
        bgj, b_st = basins.fetch(refresh=args.refresh and not args.skip_net)
        write("basins.geojson", bgj, manifest, "basins", "ok",
              note="%d HELCOM level-2 sub-basins (the division HELCOM uses in "
                   "its HOLAS assessments), grouped into the 7 major basins of "
                   "the Baltic Sea Action Plan nutrient ceilings. Simplified "
                   "from %d to %d vertices for the browser"
                   % (b_st["basins"], b_st["vertices_in"], b_st["vertices_out"]),
              features=b_st["basins"])
    except Exception as exc:
        LOG.warning("basins: %s", exc)
        write("basins.geojson", {"type": "FeatureCollection", "features": []},
              manifest, "basins", "no data", note="HELCOM MapServer: %s" % exc)

    # ------------------------------------------------------- 3 batimetría
    grid = None
    coast_idx = None
    grid_cache = os.path.join(CACHE, "depth_grid_%s.json"
                              % str(args.depth_step).replace(".", ""))
    try:
        if args.skip_net and not os.path.exists(grid_cache):
            raise RuntimeError("--skip-net y no hay rejilla en caché")
        grid, g_st = bathymetry.fetch_grid(AOI, step=args.depth_step,
                                          refresh=args.refresh and not args.skip_net,
                                          cache_path=grid_cache)
        manifest["stats"]["bathymetry"] = g_st
        # Costa e isobatas: de HELCOM, no derivadas. Se derivaban del DTM con
        # marching squares sobre la rejilla de trabajo, o sea a ~3 km, y
        # HELCOM publica las dos medidas. El indice costero que usa IND-03
        # para suprimir merodeos pegados a tierra se construye con ESA costa,
        # asi que el indicador tambien mejora, no solo el dibujo.
        # La costa de HELCOM se usa aqui para construir el indice costero de
        # IND-03, pero NO se escribe a viewer/data: el navegador la pide por
        # recuadros al abrirse y la cachea el proxy. Una sola descarga, dos
        # consumidores, cero duplicado en disco. Esta llamada toca la misma
        # cache de red que servira al visor, asi que normalmente ni baja.
        coast, c_st = helcom.coastline(AOI, refresh=args.refresh and not args.skip_net)
        coast_idx = geo.SegmentIndex()
        for seg in helcom.segments(coast):
            coast_idx.add_polyline(seg, "coast")
        manifest["stats"]["coast_index"] = {
            "source": "helcom_coastline", "features": c_st["features"],
            "segments": len(coast_idx.segs),
            "note": "built here for IND-03 coastal suppression; not shipped, "
                    "the viewer fetches the same source on demand"}
        # Isobatas: del DTM de EMODnet, NO de HELCOM. La capa 14 de HELCOM sale
        # de la BSBD y sus condiciones prohiben el uso comercial; esto es un
        # producto que se vende. Ver config/licences.toml.
        cont = bathymetry.contours(grid, paths.build_opt("isobaths_m"))
        # Rejilla de profundidad submuestreada para el visor: permite decir
        # "este buque esta sobre X m de agua" sin pedir nada a la red. Se carga
        # al arrancar, asi que el paso se escala con el AOI: en el golfo son
        # ~6.5k celdas, y en el Baltico entero al mismo paso serian 100k y
        # megas de JSON bloqueando el primer pintado.
        try:
            k = max(1, int(round(args.viewer_depth_step / grid.step)))
            nx2 = (grid.nx + k - 1) // k
            ny2 = (grid.ny + k - 1) // k
            vals2 = []
            for j in range(ny2):
                for i in range(nx2):
                    v = grid.vals[min(grid.ny - 1, j * k) * grid.nx + min(grid.nx - 1, i * k)]
                    vals2.append(None if v is None else round(v, 1))
            write("depth_grid.json",
                  {"lon0": grid.lon0, "lat0": grid.lat0, "step": grid.step * k,
                   "nx": nx2, "ny": ny2, "vals": vals2,
                   "attribution": LICENCES["emodnet"]},
                  manifest, "depth_grid", "ok",
                  note="%dx%d grid at %.3f deg for depth lookup in the viewer"
                       % (nx2, ny2, grid.step * k),
                  cells=nx2 * ny2)
        except Exception as exc:  # la rejilla es un extra, no bloquea el build
            LOG.warning("depth_grid: %s", exc)
        # La IMAGEN de profundidad, en cambio, se emite a resolucion NATIVA.
        # El submuestreo de arriba existe porque depth_grid.json se parsea al
        # arrancar; un PNG no se pide hasta que encienden la capa, asi que ahi
        # la restriccion no aplica y seria absurdo tirar la mitad del detalle.
        try:
            # Desde los GeoTIFF nativos (~116 m), no desde `grid`: ya estan en
            # la cache de red porque fetch_grid acaba de usarlos, asi que no
            # cuesta descarga. La rejilla de trabajo es de 0,03 grados y se
            # veia pixelada. `render(grid)` queda como respaldo si falta algun
            # bloque.
            try:
                blob, dm_st = depthmap.render_native(AOI, width=4096)
            except Exception as exc:
                LOG.warning("depth_map nativo: %s; se usa la rejilla", exc)
                blob, dm_st = depthmap.render(grid, width=4096)
            with open(os.path.join(OUT, "depth_map.png"), "wb") as fh:
                fh.write(blob)
            write("depth_map.json", dm_st, manifest, "depth_map", "ok",
                  note="%dx%d px, %.0f m/px, %.0f kB PNG, already projected to "
                       "EPSG:3857. Same EMODnet DTM as the WMS, read at its "
                       "native ~116 m and repainted with nine quantile bands of "
                       "Baltic depth, because the official 6,000 m ramp leaves "
                       "the whole sea in one colour. Land carries no value and "
                       "stays transparent"
                       % (dm_st["nx"], dm_st["ny"],
                          (dm_st["lon1"] - dm_st["lon0"]) / dm_st["nx"] * 111320 * 0.5,
                          len(blob) / 1024.0),
                  cells=dm_st["sea_cells"])
        except Exception as exc:
            LOG.warning("depth_map: %s", exc)
        write("isobaths.geojson", cont, manifest, "bathymetry", "ok",
              note="isobaths %s m derived from the EMODnet DTM at %.3f deg "
                   "(%d water cells). NOT HELCOM's contour layer: that one "
                   "comes from the BSBD and prohibits commercial use. EMODnet "
                   "publishes contours too but they start at 50 m, and 20 m is "
                   "the level that decides whether an anchor reaches the bed"
                   % (paths.build_opt("isobaths_m"), args.depth_step,
                      g_st["wet_cells"]),
              levels=paths.build_opt("isobaths_m"),
              grid=[g_st["nx"], g_st["ny"]], wet_cells=g_st["wet_cells"])
    except Exception as exc:
        LOG.error("batimetría: %s", exc)
        write("isobaths.geojson", {"type": "FeatureCollection", "features": []},
              manifest, "bathymetry", "no data", note="EMODnet WCS: %s" % exc)
        write("coastline.geojson", {"type": "FeatureCollection", "features": []},
              manifest, "coastline", "no data",
              note="depends on the EMODnet grid: %s" % exc)

    # ------------------------------------------------------- 4 Sentinel-1
    scenes, s_st = [], {}
    if args.skip_net:
        write("scenes.geojson", {"type": "FeatureCollection", "features": []},
              manifest, "sentinel1", "no data", note="--skip-net")
    else:
        try:
            start = dt.datetime.fromtimestamp(dataset_start / 1000, dt.timezone.utc) \
                - dt.timedelta(hours=6)
            end = dt.datetime.fromtimestamp(dataset_end / 1000, dt.timezone.utc) \
                + dt.timedelta(hours=6)
            scenes, s_st = sentinel.search(
                AOI, start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                limit=args.scenes, refresh=args.refresh)
            qdir = os.path.join(OUT, "quicklooks")
            quick = {}
            for it in scenes:
                nm = sentinel.fetch_quicklook(it, qdir, refresh=args.refresh)
                if nm:
                    quick[it["id"]] = "quicklooks/" + nm
            s_st["quicklooks"] = len(quick)

            # correlación AIS <-> escena: buques dentro del footprint +/- 30 min
            fc = sentinel.to_geojson(scenes, quick)
            for f in fc["features"]:
                t = f["properties"]["datetime"]
                tms = dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() * 1000
                ring = f["geometry"]["coordinates"][0] if f["geometry"] else []
                if f["geometry"] and f["geometry"]["type"] == "MultiPolygon":
                    ring = f["geometry"]["coordinates"][0][0]
                inside = set()
                for fx in fixes:
                    if abs(fx["ts"] - tms) <= 1800_000 and ring and \
                       geo.point_in_ring(fx["lon"], fx["lat"], ring):
                        inside.add(fx["mmsi"])
                f["properties"]["ais_vessels_in_footprint_pm30min"] = len(inside)
                f["properties"]["ais_mmsi_in_footprint"] = sorted(inside)[:200]
                f["properties"]["sar_detections"] = None
                f["properties"]["sar_detections_note"] = (
                    "no calculado: exige el GRD completo, que requiere cuenta CDSE")

            # intento real de descarga del producto
            dl_note, dl_ok = None, 0
            if scenes and not args.grd:
                dl_note = ("GRD no descargado (usa --grd). El visor pinta SAR "
                           "georreferenciado via Planetary Computer sin credenciales; "
                           "el SAFE solo hace falta para deteccion local.")
            elif scenes:
                path, why = sentinel.download_product(scenes[0], os.path.join(CACHE, "s1"),
                                                      creds_path=CREDS)
                if path:
                    dl_ok = 1
                    dl_note = "descargado %s" % os.path.basename(path)
                else:
                    dl_note = why
            ov = [f["properties"]["ais_vessels_in_footprint_pm30min"]
                  for f in fc["features"]]
            s_st["scenes_with_ais_overlap"] = sum(1 for n in ov if n > 0)
            s_st["ais_vessels_in_footprints_total"] = sum(ov)
            s_st["overlap_note"] = (
                "El solape AIS<->escena solo existe si el grabador estaba "
                "corriendo a la hora de la pasada. Sentinel-1 pasa ~2 veces/día "
                "sobre el golfo; el grabador ha estado parado la mayor parte del "
                "tiempo. Para tipping-and-cueing real hay que dejarlo corriendo "
                "en continuo (unidad systemd de D1, sin instalar).")
            s_st["product_download"] = dl_note
            manifest["stats"]["sentinel1"] = s_st
            write("scenes.geojson", fc, manifest, "sentinel1",
                  "ok" if scenes else "no data",
                  note="%d scenes in the catalogue, %d public quicklooks "
                       "descargados, %d escenas con solape AIS (±30 min); "
                       "GRD completo: %s"
                       % (len(scenes), len(quick),
                          s_st["scenes_with_ais_overlap"], dl_note),
                  scenes=len(scenes), quicklooks=len(quick),
                  grd_downloaded=dl_ok)
        except Exception as exc:
            LOG.error("Sentinel-1: %s", exc)
            write("scenes.geojson", {"type": "FeatureCollection", "features": []},
                  manifest, "sentinel1", "no data", note="STAC: %s" % exc)

    # --------------------------------------------- 4b Global Fishing Watch
    # Segunda opinion independiente sobre el mismo comportamiento que ya
    # medimos: GAP es IND-04 calculado por otro equipo. Coincidir con GFW
    # convierte una alerta propia en una alerta corroborada; no coincidir es
    # igual de informativo y por eso se guarda entera, no filtrada.
    if args.skip_net or args.gfw_days <= 0:
        write("gfw_events.geojson", {"type": "FeatureCollection", "features": []},
              manifest, "gfw_events", "no data",
              note="--skip-net" if args.skip_net else "--gfw-days 0")
    elif not gfw.token():
        write("gfw_events.geojson", {"type": "FeatureCollection", "features": []},
              manifest, "gfw_events", "no data",
              note="GFW_TOKEN missing from secrets.env. Free token at "
                   "globalfishingwatch.org/our-apis/tokens")
    else:
        try:
            g_end = dt.datetime.now(dt.timezone.utc).date()
            g_start = g_end - dt.timedelta(days=args.gfw_days)
            types = [x.strip().upper() for x in args.gfw_events.split(",") if x.strip()]
            g_fc, g_st = gfw.collect(AOI, g_start.isoformat(), g_end.isoformat(),
                                     types=types, refresh=args.refresh)
            manifest["stats"]["gfw"] = g_st
            n_gfw = len(g_fc["features"])
            write("gfw_events.geojson", g_fc, manifest, "gfw_events",
                  "ok" if n_gfw else "empty",
                  note="%d events %s, %s..%s. CC BY-SA 4.0, attribution required."
                       % (n_gfw, "/".join(types), g_start, g_end),
                  events=n_gfw, window_days=args.gfw_days,
                  by_type={k: v.get("returned", 0) for k, v in g_st["types"].items()})
        except Exception as exc:
            LOG.error("GFW: %s", exc)
            write("gfw_events.geojson", {"type": "FeatureCollection", "features": []},
                  manifest, "gfw_events", "no data", note="GFW API: %s" % exc)

    # -------------------------------------------- 4c rejillas 4wings de GFW
    # El mapa de calor de la web de GFW. Lo que se trae por defecto NO es
    # pesca sino PRESENCIA: horas de cualquier buque por celda, que es la
    # linea base de trafico normal. Sin linea base, todos los indicadores de
    # este proyecto son absolutos; con ella se puede comparar un dia contra
    # su propia historia.
    grids = [g.strip().lower() for g in (args.gfw_grid or "").split(",")
             if g.strip() and g.strip().lower() != "none"]
    if args.skip_net or not grids or args.gfw_days <= 0:
        write("gfw_grid.geojson", {"type": "FeatureCollection", "features": []},
              manifest, "gfw_grid", "no data",
              note="--skip-net" if args.skip_net else "desactivado (--gfw-grid none)")
    elif not gfw.token():
        write("gfw_grid.geojson", {"type": "FeatureCollection", "features": []},
              manifest, "gfw_grid", "no data", note="GFW_TOKEN missing")
    else:
        g_end = dt.datetime.now(dt.timezone.utc).date()
        g_start = g_end - dt.timedelta(days=min(args.gfw_days, 366))
        all_feats, g_notes, g_stats = [], [], {}
        for kind in grids:
            try:
                # SAR: lo valioso es la deteccion SIN AIS emparejado, que es
                # literalmente un buque oscuro. Se pide ya filtrado.
                flt = "matched = 'false'" if kind == "sar" else None
                rows, rst = gfw.report(kind, AOI, g_start.isoformat(), g_end.isoformat(),
                                       spatial=args.gfw_grid_res, temporal="MONTHLY",
                                       filter_by=flt, refresh=args.refresh)
                fc_g, note = gfw.grid_to_geojson(rows, args.gfw_grid_res)
                for f in fc_g["features"]:
                    f["properties"]["grid"] = kind
                all_feats.extend(fc_g["features"])
                rst["note"] = note
                g_stats[kind] = rst
                g_notes.append("%s=%d (%s)" % (kind, len(fc_g["features"]), note))
            except Exception as exc:                        # noqa: BLE001
                g_stats[kind] = {"error": str(exc)[:200]}
                g_notes.append("%s FALLO: %s" % (kind, str(exc)[:80]))
                LOG.warning("GFW rejilla %s: %s", kind, str(exc)[:160])
        manifest["stats"]["gfw_grid"] = g_stats
        write("gfw_grid.geojson",
              {"type": "FeatureCollection", "features": all_feats},
              manifest, "gfw_grid", "ok" if all_feats else "empty",
              note="%s, %s..%s, resolution %s. CC BY-SA 4.0."
                   % ("; ".join(g_notes), g_start, g_end, args.gfw_grid_res),
              cells=len(all_feats), grids=grids, resolution=args.gfw_grid_res)

    # -------------------------------- 4d2 restricciones del resto del Baltico
    # Vaylavirasto solo cubre Finlandia. Con el AOI en el golfo eso era casi
    # todo el mapa; con el AOI en el Baltico es una franja, y decir "hay cable
    # y no hay prohibicion de fondeo" pasaria a ser una afirmacion sobre
    # Finlandia disfrazada de afirmacion sobre el Baltico.
    msp_fc, msp_mask = None, None
    cov = authorities.coverage()
    manifest["stats"]["authorities"] = cov
    if args.skip_net:
        write("msp_restricted.geojson", {"type": "FeatureCollection", "features": []},
              manifest, "msp_restricted", "no data", note="--skip-net")
    else:
        try:
            msp_fc, msp_st = authorities.helcom_msp(AOI, refresh=args.refresh)
            msp_mask = authorities.mask_of(msp_fc)
            manifest["stats"]["msp"] = msp_st
            nb = sum(1 for f in msp_fc["features"]
                     if f["properties"].get("bottom_impact_forbidden"))
            write("msp_restricted.geojson", msp_fc, manifest, "msp_restricted",
                  "ok" if msp_fc["features"] else "empty",
                  note="%d restricted-use areas from the maritime spatial plans of %s; "
                       "%d forbid something that touches the seabed. Source: "
                       "HELCOM MADS."
                       % (msp_st["areas"],
                          "/".join(sorted(msp_st["by_country"])), nb),
                  areas=msp_st["areas"], by_country=msp_st["by_country"],
                  bottom_impact_forbidden=nb,
                  countries_without_data=[m["cc"] for m in cov["missing"]])
            LOG.info("cobertura juridica: %d de %d ribereños con dato (%s); "
                     "sin dato: %s", cov["countries_wired"], cov["countries_total"],
                     ",".join(cov["wired"]),
                     ",".join(m["cc"] for m in cov["missing"]))
        except Exception as exc:
            LOG.error("HELCOM MSP: %s", exc)
            write("msp_restricted.geojson", {"type": "FeatureCollection", "features": []},
                  manifest, "msp_restricted", "no data", note="HELCOM MSP: %s" % exc)

    # ------------------------------------------------ 4e fondo y restricciones
    # Tres capas de EMODnet Human Activities que contestan preguntas que el
    # visor ya se hacia: que hay en el fondo (pecios), donde es NORMAL que un
    # buque de guerra se mueva despacio (areas de defensa) y donde fondear es
    # un delito ademas de una mala idea (vertederos de municion).
    wreck_fc, mil_fc, mun_fc = None, None, None
    wreck_idx, mil_mask, mun_mask = [], None, None
    if args.skip_net or args.no_seabed:
        for name, lyr in (("wrecks.geojson", "wrecks"),
                          ("military_areas.geojson", "military_areas"),
                          ("munitions.geojson", "munitions")):
            write(name, {"type": "FeatureCollection", "features": []}, manifest, lyr,
                  "no data", note="--skip-net" if args.skip_net else "--no-seabed")
    else:
        sb_st = {}
        try:
            wreck_fc, w_st = seabed.wrecks(AOI, refresh=args.refresh)
            sb_st["wrecks"] = w_st
            wreck_idx = seabed.wreck_index(wreck_fc)
            write("wrecks.geojson", wreck_fc, manifest, "wrecks",
                  "ok" if wreck_fc["features"] else "empty",
                  note="%d wrecks, %d catalogued dangerous, %d submarines%s"
                       % (w_st["returned"], w_st["dangerous"], w_st["submarines"],
                          ". " + w_st["warning"] if w_st.get("warning") else ""),
                  wrecks=w_st["returned"], submarines=w_st["submarines"])
        except Exception as exc:
            LOG.error("pecios: %s", exc)
            write("wrecks.geojson", {"type": "FeatureCollection", "features": []},
                  manifest, "wrecks", "no data", note="EMODnet HA: %s" % exc)
        try:
            mil_fc, m_st = seabed.military_areas(AOI, refresh=args.refresh)
            sb_st["military"] = m_st
            mil_mask = seabed.mask_of(mil_fc)
            write("military_areas.geojson", mil_fc, manifest, "military_areas",
                  "ok" if mil_fc["features"] else "empty",
                  note="%d declared national defence areas" % m_st["returned"],
                  areas=m_st["returned"])
        except Exception as exc:
            LOG.error("areas militares: %s", exc)
            write("military_areas.geojson", {"type": "FeatureCollection", "features": []},
                  manifest, "military_areas", "no data", note="EMODnet HA: %s" % exc)
        try:
            mun_fc, u_st = seabed.munitions(AOI, refresh=args.refresh)
            sb_st["munitions"] = u_st
            mun_mask = seabed.mask_of(mun_fc)
            write("munitions.geojson", mun_fc, manifest, "munitions",
                  "ok" if mun_fc["features"] else "empty",
                  note="%d munitions dumping grounds (HELCOM via EMODnet)"
                       % u_st["returned"], areas=u_st["returned"])
        except Exception as exc:
            LOG.error("municion: %s", exc)
            write("munitions.geojson", {"type": "FeatureCollection", "features": []},
                  manifest, "munitions", "no data", note="EMODnet HA: %s" % exc)
        # Por que esta area es especial. No se inventa: se calcula contra lo
        # que ya hay en el build, asi que cualquiera puede comprobarlo con los
        # mismos ficheros.
        if mil_fc and mil_fc["features"]:
            try:
                seabed.justify_areas(
                    mil_fc,
                    corridors={"type": "FeatureCollection", "features": trunk}
                              if n_trunk else None,
                    wrecks_fc=wreck_fc, restrictions=res_fc,
                    depth_grid=grid, tracks=tracks)
                write("military_areas.geojson", mil_fc, manifest, "military_areas", "ok",
                      note="%d declared national defence areas from %s, each with an inventory "
                           "of what lies inside it"
                           % (len(mil_fc["features"]),
                              "/".join(sorted({(f["properties"].get("country") or "?")
                                               for f in mil_fc["features"]}))),
                      areas=len(mil_fc["features"]))
                withc = sum(1 for f in mil_fc["features"]
                            if (f["properties"].get("why") or {}).get("corridors"))
                bans = sum((f["properties"].get("why") or {}).get("anchoring_bans_inside", 0)
                           for f in mil_fc["features"])
                sb_st["military_justified"] = {"areas": len(mil_fc["features"]),
                                               "with_corridor": withc,
                                               "anchor_bans_inside_total": bans}
                LOG.info("areas de defensa: %d de %d contienen un corredor troncal; "
                         "%d prohibiciones de fondeo dentro en total",
                         withc, len(mil_fc["features"]), bans)
            except Exception as exc:                     # noqa: BLE001
                LOG.warning("justificacion de areas: %s", str(exc)[:160])
        manifest["stats"]["seabed"] = sb_st

    # ----------------------------------------------- 4d dossier de buques
    # Lo que YA estaba en el almacen y nadie usaba: referencePointA..D dan
    # eslora y manga exactas sin salir a la red. Encima van las sanciones,
    # que para un producto de defensa pesan mas que una foto.
    try:
        vinfo, v_st = vesselinfo.build(
            vessels, use_net=not (args.skip_net or args.no_vessel_info),
            refresh=args.refresh, wikidata_limit=args.wikidata_limit)
        manifest["stats"]["vessel_info"] = v_st
        n_dim = sum(1 for r in vinfo.values() if r["dimensions"].get("length_m"))
        n_san = sum(1 for r in vinfo.values() if r.get("sanctions"))
        n_pic = sum(1 for r in vinfo.values()
                    if (r.get("reference") or {}).get("image"))
        write("vessel_info.json", vinfo, manifest, "vessel_info",
              "ok" if vinfo else "empty",
              note="%d vessels; %d with length from AIS; %d on sanctions lists; "
                   "%d with a Wikimedia Commons photo"
                   % (len(vinfo), n_dim, n_san, n_pic),
              vessels=len(vinfo), with_dimensions=n_dim, sanctioned=n_san,
              with_photo=n_pic)
        if n_san:
            LOG.warning("%d buques del AOI aparecen en listas de sanciones", n_san)
    except Exception as exc:
        LOG.error("dossier de buques: %s", exc)
        write("vessel_info.json", {}, manifest, "vessel_info", "no data",
              note="vesselinfo: %s" % exc)

    # ------------------------------------------------------- 5 indicadores
    if n_trunk == 0:
        LOG.warning("sin corredores trunk: IND-01 e IND-05 no pueden disparar")
    alerts, ind_st = indicators.run(tracks, corridor_idx, grid, coverage, dataset_end,
                                    port_mask=port_mask if len(port_mask) else None,
                                    vessels=vessels, coast_idx=coast_idx, aoi=AOI)
    ind_st["trunk_polylines_indexed"] = n_trunk
    ind_st["depth_grid"] = bool(grid)
    ind_st["coast_index_segments"] = len(coast_idx.segs) if coast_idx else 0
    manifest["stats"]["indicators"] = ind_st

    # Marca jurídica: ¿el punto de la alerta cae dentro de un área de
    # prohibición de fondeo publicada por Väylävirasto? Con su diaarinumero
    # cuando lo hay. Es lo que separa «sospechoso» de «oponible».
    n_ban = 0
    for a in alerts:
        hit = ban_mask.hit(a["lon"], a["lat"]) if len(ban_mask) else None
        a["evidence"]["anchoring_prohibited_area"] = hit
        if hit:
            n_ban += 1
    ind_st["alerts_inside_anchor_ban_area"] = n_ban
    ind_st["anchor_ban_areas_in_aoi"] = len(ban_mask)

    # Contexto del fondo y de las zonas declaradas. Se ANOTA, no se suprime:
    # un buque de guerra despacio dentro de un area de defensa nacional sigue
    # siendo un dato, solo que deja de ser una anomalia. Quien lee decide.
    n_mil = n_mun = n_wreck = 0
    for a in alerts:
        e = a["evidence"]
        hit = mil_mask.hit(a["lon"], a["lat"]) if mil_mask and len(mil_mask) else None
        e["military_area"] = hit
        if hit:
            n_mil += 1
        hit = mun_mask.hit(a["lon"], a["lat"]) if mun_mask and len(mun_mask) else None
        e["munitions_area"] = hit
        if hit:
            n_mun += 1
        w = seabed.nearest_wreck(wreck_idx, a["lon"], a["lat"]) if wreck_idx else None
        if w:
            e["nearest_wreck"] = {"name": w[0], "distance_m": w[1], "dangerous": w[2]}
            n_wreck += 1
        else:
            e["nearest_wreck"] = None
    ind_st["alerts_inside_military_area"] = n_mil
    ind_st["alerts_inside_munitions_area"] = n_mun
    ind_st["alerts_near_known_wreck"] = n_wreck
    if n_mil:
        LOG.info("%d alertas caen dentro de un area de defensa nacional declarada", n_mil)
    if n_wreck:
        LOG.info("%d alertas a menos de %.0f m de un pecio conocido",
                 n_wreck, seabed.WRECK_NEAR_M)

    # procedencia de profundidad en los puntos de alerta (EMODnet depth_sample)
    prov = []
    if not args.skip_net and alerts:
        pts = [(a["lon"], a["lat"]) for a in alerts[:args.depth_samples]]
        prov = bathymetry.sample_points(pts, budget=args.depth_samples,
                                        refresh=args.refresh)
        bykey = {(round(p["lon"], 6), round(p["lat"], 6)): p for p in prov}
        for a in alerts:
            p = bykey.get((round(a["lon"], 6), round(a["lat"], 6)))
            if p:
                a["evidence"]["depth_m_emodnet"] = p["depth_m"]
                a["evidence"]["depth_dtm"] = p["dtm"]
                a["evidence"]["depth_dtm_metadata_url"] = p["dtm_metadata_url"]
                a["evidence"]["depth_interpolated"] = p["interpolated"]
    ind_st["depth_provenance_points"] = len(prov)

    prov = {
        "built_utc": manifest["built_utc"],
        "ais_source": LICENCES["ais"],
        "ais_store": " + ".join(args.ais_root),
        "ais_stores": list(args.ais_root),
        "ais_files": ais_st["files"],
        "ais_span_utc": ais_st["ais_span_utc"],
        "coverage_windows_ms": [[int(a), int(b)] for a, b in coverage],
        "dataset_start_ms": int(dataset_start), "dataset_end_ms": int(dataset_end),
        "built_epoch_ms": int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000),
        "ais_coverage_seconds": ais_st["coverage_seconds"],
        "corridors_source": "OSM Overpass",
        "corridors_osm_timestamp": corr_st.get("osm_timestamp"),
        "bathymetry_coverage": bathymetry.COVERAGE,
        "bathymetry_grid_step_deg": args.depth_step,
        "bathymetry_source": LICENCES["emodnet"],
        "restrictions_source": LICENCES["vayla"],
        "indicators_not_implemented": indicators.NOT_IMPLEMENTED,
    }
    # Capa de supresiones: que ha enmascarado el filtro y donde. Sin esto el
    # contador "32 suprimidas" hay que creerselo.
    _ev = (ind_st.get("counters") or ind_st).pop("_events", []) if isinstance(ind_st, dict) else []
    if _ev:
        write("suppressed.geojson",
              {"type": "FeatureCollection",
               "features": [{"type": "Feature",
                             "geometry": {"type": "Point",
                                          "coordinates": [round(e["lon"], 5), round(e["lat"], 5)]},
                             "properties": {k: v for k, v in e.items()
                                            if k not in ("lon", "lat")}} for e in _ev],
               "properties": {"attribution": LICENCES["ais"]}},
              manifest, "suppressed", "ok",
              note="%d detections suppressed by the filters, each with its reason" % len(_ev),
              events=len(_ev))

    write("alerts.geojson", indicators.to_geojson(alerts, prov), manifest, "alerts",
          "ok" if alerts else "empty",
          note="%d alerts + %d exposures over %d tracks (%s)"
               % (ind_st["alerts"], ind_st["exposures"], ind_st["tracks"],
                  ", ".join("%s=%d" % kv for kv in sorted(ind_st["by_indicator"].items()))),
          alerts=ind_st["alerts"], exposures=ind_st["exposures"],
          by_indicator=ind_st["by_indicator"], calibrated=False)

    manifest["build_seconds"] = round(time.time() - t_build, 1)
    with open(os.path.join(OUT, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    LOG.info("manifest escrito. build %.1f s", manifest["build_seconds"])

    # Qué quedó y dónde. El tamaño en disco es lo que delata una capa vacía
    # que el manifest declara "ok" porque escribió un FeatureCollection sin
    # features: 0 B no existe, pero 180 B sí.
    _f = sorted(f for f in os.listdir(OUT) if f.endswith((".geojson", ".json")))
    _b = sum(os.path.getsize(os.path.join(OUT, f)) for f in _f)
    LOG.info("build en %s: %d ficheros, %.1f MB", OUT, len(_f), _b / 1e6)

    print("\n=== RESUMEN ===")
    for k, v in manifest["layers"].items():
        print("%-12s %-9s %s" % (k, v["status"], v["note"]))
    print("\nSalida:   %s  (%d ficheros, %.1f MB)" % (OUT, len(_f), _b / 1e6))
    print("Caché:    %s" % CACHE)
    print("Config:   %s" % os.path.join(HERE, "config", "custody.toml"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
