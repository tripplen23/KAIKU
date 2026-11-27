"""Batimetría EMODnet Bathymetry. Dos vías, por razones distintas.

1. WCS 2.0.1 GetCoverage (`emodnet__mean`, float32 GeoTIFF, 1/960 deg ~ 116 m):
   rejilla densa para consultar profundidad en cualquier punto sin red una vez
   cacheada, y para generar isobatas. Verificado 2026-11-09: HTTP 200,
   8,4 MB por bloque de 2 x 0,8 deg. El servidor NO soporta la extensión
   Scaling (`ScaleAxisUndefined`), asi que se pide por bloques y se submuestrea
   en local.

2. REST `depth_sample` (solo POINT): devuelve ademas la PROCEDENCIA
   (organisation_id, identifier, metadata_url del DTM o campaña concreta).
   Eso es lo que convierte una cifra de profundidad en evidencia citable, y es
   el motivo de usarlo pese a ser un punto por peticion.

Signo: positivo = altitud sobre el nivel del mar, negativo = profundidad.
Aqui se devuelve profundidad en metros POSITIVOS y None en tierra.
Atribucion: "EMODnet Bathymetry Consortium - EMODnet Digital Bathymetry (DTM)".
"""
import json
import logging
import math
import os
import time
import urllib.parse

from . import net, tiff

LOG = logging.getLogger("custody.bathy")
WCS = "https://ows.emodnet-bathymetry.eu/wcs"
REST = "https://rest.emodnet-bathymetry.eu/depth_sample"
# El WMS (ows.emodnet-bathymetry.eu/wms, capa emodnet:mean) lo consume
# directamente el visor como capa opcional de red; aquí no se usa.
ATTRIBUTION = "EMODnet Bathymetry Consortium - EMODnet Digital Bathymetry (DTM)"
COVERAGE = "emodnet__mean"


class DepthGrid:
    """Rejilla regular de profundidad. lon/lat crecientes, fila 0 = lat mínima."""

    def __init__(self, lon0, lat0, step, nx, ny, vals):
        self.lon0, self.lat0, self.step, self.nx, self.ny = lon0, lat0, step, nx, ny
        self.vals = vals  # lista nx*ny, None en tierra/sin dato

    def depth_at(self, lon, lat):
        i = int(round((lon - self.lon0) / self.step))
        j = int(round((lat - self.lat0) / self.step))
        if not (0 <= i < self.nx and 0 <= j < self.ny):
            return None
        return self.vals[j * self.nx + i]

    def to_json(self):
        return {"lon0": self.lon0, "lat0": self.lat0, "step": self.step,
                "nx": self.nx, "ny": self.ny, "attribution": ATTRIBUTION,
                "vals": self.vals}

    @staticmethod
    def from_json(d):
        return DepthGrid(d["lon0"], d["lat0"], d["step"], d["nx"], d["ny"], d["vals"])


def block_urls(bbox, block_deg=1.0):
    """Los bloques WCS que cubren el bbox, de oeste a este.

    Se expone aparte porque hay dos consumidores: fetch_grid, que submuestrea
    a la rejilla de trabajo, y depthmap, que pinta a resolucion nativa. Si
    cada uno construyera la URL por su cuenta, una diferencia de un decimal
    en el subset partiria la cache en dos y el segundo se bajaria 1 GB otra
    vez.
    """
    minlon, minlat, maxlon, maxlat = bbox
    out, lon = [], minlon
    while lon < maxlon - 1e-9:
        lon_hi = min(lon + block_deg, maxlon)
        out.append((lon, lon_hi, WCS + "?" + urllib.parse.urlencode({
            "service": "WCS", "version": "2.0.1", "request": "GetCoverage",
            "coverageId": COVERAGE, "format": "image/tiff"})
            + "&subset=Long(%.4f,%.4f)&subset=Lat(%.4f,%.4f)"
            % (lon, lon_hi, minlat, maxlat)))
        lon = lon_hi
    return out


def fetch_grid(bbox, step=0.01, block_deg=1.0, refresh=False, cache_path=None):
    """bbox = (minlon, minlat, maxlon, maxlat). Devuelve (DepthGrid, stats)."""
    if cache_path and os.path.exists(cache_path) and not refresh:
        with open(cache_path) as fh:
            d = json.load(fh)
        g = DepthGrid.from_json(d)
        return g, {"from_cache": True, "nx": g.nx, "ny": g.ny,
                   "wet_cells": sum(1 for v in g.vals if v is not None)}

    minlon, minlat, maxlon, maxlat = bbox
    nx = int(round((maxlon - minlon) / step)) + 1
    ny = int(round((maxlat - minlat) / step)) + 1
    vals = [None] * (nx * ny)
    st = {"from_cache": False, "blocks": 0, "bytes": 0, "nx": nx, "ny": ny}

    for lon, lon_hi, url in block_urls(bbox, block_deg):
        raw, cached = net.fetch(url, refresh=refresh, ext="tif", timeout=300)
        st["blocks"] += 1
        st["bytes"] += len(raw)
        if raw[:2] not in (b"II", b"MM"):
            raise RuntimeError("WCS devolvió %r en lugar de TIFF: %s"
                               % (raw[:60], url))
        t = tiff.GeoTiff(raw)
        i0 = int(math.ceil((lon - minlon) / step))
        i1 = int(math.floor((lon_hi - minlon) / step))
        # Submuestreo por media de una subrejilla 3x3 dentro de cada celda: el
        # raster es de ~116 m y la celda de ~1,1 km. Tomar un solo pixel haría
        # que un bajo aislado decidiera la celda entera.
        sub = [-step / 3.0, 0.0, step / 3.0]
        for i in range(max(0, i0), min(nx - 1, i1) + 1):
            glon = minlon + i * step
            for j in range(ny):
                glat = minlat + j * step
                acc, n = 0.0, 0
                for dx in sub:
                    for dy in sub:
                        v = t.value_at(glon + dx, glat + dy)
                        if v is not None:
                            acc += v
                            n += 1
                if n == 0:
                    continue
                v = acc / n
                vals[j * nx + i] = None if v >= 0.0 else round(-v, 1)
        LOG.info("batimetría bloque Long(%.2f,%.2f) %s %d B", lon, lon_hi,
                 "cache" if cached else "red", len(raw))

    g = DepthGrid(minlon, minlat, step, nx, ny, vals)
    st["wet_cells"] = sum(1 for v in vals if v is not None)
    if cache_path:
        with open(cache_path, "w") as fh:
            json.dump(g.to_json(), fh, separators=(",", ":"))
    return g, st


def depth_sample(lon, lat, refresh=False):
    """Profundidad puntual CON procedencia. Devuelve dict o None."""
    url = REST + "?" + urllib.parse.urlencode({"geom": "POINT(%.6f %.6f)" % (lon, lat)})
    try:
        doc, cached = net.fetch_json(url, refresh=refresh, timeout=60, retries=1)
    except Exception as exc:
        LOG.warning("depth_sample %.4f,%.4f falló: %s", lon, lat, exc)
        return None
    if "avg" not in doc:
        return None
    ref = doc.get("reference") or {}
    return {"lon": lon, "lat": lat,
            "depth_m": None if doc["avg"] >= 0 else round(-doc["avg"], 2),
            "elev_m": round(doc["avg"], 2),
            "stdev": doc.get("stdev"),
            "interpolated": bool(doc.get("interpolationType")),
            "dtm": ref.get("identifier"), "dtm_type": ref.get("type"),
            "dtm_org_id": ref.get("organisation_id"),
            "dtm_metadata_url": ref.get("metadata_url"),
            "_cached": cached}


def sample_points(points, sleep_s=0.15, refresh=False, budget=400):
    """Llama a depth_sample sobre una lista acotada de puntos. Educado: 1 req
    cada sleep_s y tope duro `budget` peticiones por ejecución."""
    out = []
    used = 0
    for lon, lat in points:
        if used >= budget:
            LOG.warning("presupuesto depth_sample agotado en %d puntos", budget)
            break
        r = depth_sample(lon, lat, refresh=refresh)
        used += 1
        if r:
            out.append(r)
            if not r.get("_cached"):
                time.sleep(sleep_s)
    return out


# ---------------------------------------------------------------- isobatas


# LA COSTA SE FUE A HELCOM; LAS ISOBATAS VOLVIERON AQUI, Y POR LICENCIA.
#
# `landmask_contour()` se borro: HELCOM publica la costa medida, a 8 m entre
# vertices en vez de a los ~3 km de esta rejilla, y su licencia permite uso
# comercial citando la fuente. Vive en custody/helcom.py.
#
# `contours()` tambien se borro, y hubo que traerlo de vuelta. Las isobatas de
# HELCOM (capa 14) salen de la Baltic Sea Bathymetry Database, cuyas
# condiciones dicen literalmente «available for scientific research only [...]
# Any commercial use is prohibited». Esto es un producto que se vende, asi que
# esa capa no se puede usar y punto.
#
# La alternativa publicada --EMODnet Bathymetric Contours-- solo trae 50, 100,
# 200, 500 m y mas hondos. Nos falta el nivel de 20 m, que es justo el que
# decide si un ancla alcanza el fondo, o sea la pregunta de todo el producto.
#
# Asi que se derivan del DTM de EMODnet, que es CC-BY 4.0 y permite uso
# comercial con atribucion. Es la unica via que da 20 m con licencia limpia.


def contours(grid, levels):
    """Isolineas por marching squares sobre la rejilla de profundidad.

    Celda a celda, se mira en que aristas cruza el nivel y se emite el
    segmento correspondiente. No se cierran ni se ordenan los anillos: para
    dibujar una isobata no hace falta topologia, y mantenerla cuesta mas que
    lo que aporta.

    Las celdas sin dato (tierra) no participan: una arista con un extremo
    None no se interpola, se descarta. Si no, la costa saldria como isobata.
    """
    feats = []
    for lv in levels:
        segs = []
        for j in range(grid.ny - 1):
            for i in range(grid.nx - 1):
                v = [grid.vals[j * grid.nx + i],
                     grid.vals[j * grid.nx + i + 1],
                     grid.vals[(j + 1) * grid.nx + i + 1],
                     grid.vals[(j + 1) * grid.nx + i]]
                if any(x is None for x in v):
                    continue
                lon0 = grid.lon0 + i * grid.step
                lat0 = grid.lat0 + j * grid.step
                xy = [(lon0, lat0), (lon0 + grid.step, lat0),
                      (lon0 + grid.step, lat0 + grid.step), (lon0, lat0 + grid.step)]
                pts = []
                for k in range(4):
                    a, b = v[k], v[(k + 1) % 4]
                    if (a < lv) == (b < lv):
                        continue
                    t = (lv - a) / (b - a) if b != a else 0.5
                    pa, pb = xy[k], xy[(k + 1) % 4]
                    pts.append([round(pa[0] + t * (pb[0] - pa[0]), 5),
                                round(pa[1] + t * (pb[1] - pa[1]), 5)])
                # 2 cortes = un segmento. 4 = celda en silla de montar: se
                # emiten los dos pares en el orden en que salen, que para
                # dibujar basta y evita elegir mal la diagonal.
                for k in range(0, len(pts) - 1, 2):
                    segs.append([pts[k], pts[k + 1]])
        feats.append({"type": "Feature",
                      "geometry": {"type": "MultiLineString", "coordinates": segs},
                      "properties": {"depth_m": lv, "segments": len(segs)}})
    return {"type": "FeatureCollection", "features": feats,
            "properties": {"attribution": ATTRIBUTION, "levels": levels}}
