"""Mapa de profundidad del Baltico con paleta propia.

La escala oficial de EMODnet va de -6000 m a 0 y el servicio ignora
COLORSCALERANGE, asi que no hay forma de reescalarla desde fuera. Medido sobre
nuestra propia rejilla, la mediana del Baltico son 48 m y el 85 % del mar es
mas somero que 120 m: con esa rampa todo el mar cae en el ultimo 2 % de la
escala y medio espectro se gasta en fosas que aqui no existen.

Aqui se repinta el mismo DTM con cortes elegidos por CUANTILES del dato, que
es lo que reparte el contraste donde hay informacion. Se emite un PNG en vez
de JSON: son nueve colores planos, comprime a una fraccion de lo que ocupa la
rejilla en texto, y el visor solo lo pide si encienden la capa.

Un unico corte no es estadistico: los 100 m, donde deja de ser practico
fondear un mercante. Es la pregunta que hace toda la herramienta, asi que la
escala tiene una banda que termina ahi.

DOS COSAS QUE LA PRIMERA VERSION HACIA MAL
------------------------------------------
1. PROYECCION. Leaflet estira un ImageOverlay LINEALMENTE sobre el rectangulo
   proyectado, y el mapa es Web Mercator. Las filas iban equiespaciadas en
   LATITUD, que en Mercator no es lineal: entre 53,5 y 66 N el error llegaba a
   66 km en el centro de la imagen y era cero en los bordes, que es justo el
   aspecto de "estirado y desplazado" respecto de las demas capas. Aqui las
   filas se espacian en Y DE MERCATOR y se convierten a latitud al muestrear.
2. RESOLUCION. Se pintaba desde la rejilla de trabajo de 0,03 grados (~3 km)
   cuando los GeoTIFF nativos de EMODnet, de ~116 m, ya estaban en la cache de
   red. Ahora se leen esos: misma descarga, treinta veces mas detalle.
"""
import json
import math
import struct
import zlib

# (profundidad maxima de la banda, RGB, etiqueta). Cortes por cuantiles del
# Baltico; ninguna banda baja del 3 % ni pasa del 19 % del area.
BANDS = [
    (10,   (214, 240, 231), "0-10 m"),
    (20,   (143, 217, 192), "10-20 m"),
    (30,   (79, 195, 161),  "20-30 m"),
    (50,   (42, 157, 143),  "30-50 m"),
    (80,   (42, 127, 158),  "50-80 m"),
    (120,  (43, 95, 158),   "80-120 m"),
    (200,  (59, 63, 143),   "120-200 m"),
    (300,  (91, 47, 143),   "200-300 m"),
    (1e9,  (142, 47, 158),  "300 m +"),
]
ANCHOR_LIMIT_M = 100.0


def _png(pixels, nx, ny):
    """PNG indexado (color type 3) de 10 entradas: 9 bandas + tierra.

    Indexado y no RGBA porque el dato ES categorico: nueve colores planos. El
    fichero sale ~1 byte por pixel antes de comprimir en vez de 4, y sobre
    todo se evita que el navegador tenga que interpolar entre valores que no
    significan nada.
    """
    pal = b"".join(struct.pack("BBB", *c) for _, c, _ in BANDS) + b"\0\0\0"
    # La ultima entrada es la tierra: transparente. El resto, opacas.
    trns = b"\xff" * len(BANDS) + b"\x00"
    raw = bytearray()
    for j in range(ny):
        raw.append(0)                      # filtro None por fila
        raw.extend(pixels[j * nx:(j + 1) * nx])

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", nx, ny, 8, 3, 0, 0, 0))
            + chunk(b"PLTE", pal)
            + chunk(b"tRNS", trns)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def _merc_y(lat):
    return math.log(math.tan(math.radians(45.0 + lat / 2.0)))


def _lat_of(y):
    return 2.0 * (math.degrees(math.atan(math.exp(y))) - 45.0)


def _mercator_lats(lat0, lat1, ny):
    """Latitudes de cada fila, de ARRIBA (lat1) a abajo, lineales en Mercator.

    Esto es lo que hace que la capa cuadre con el mapa. Ver cabecera.
    """
    y0, y1 = _merc_y(lat0), _merc_y(lat1)
    return [_lat_of(y1 - (y1 - y0) * (r + 0.5) / ny) for r in range(ny)]


def _classify(v):
    """Profundidad en metros (positiva) -> indice de banda. None = tierra."""
    if v is None or v != v or v <= 0:
        return None
    for k, (top, _, _) in enumerate(BANDS):
        if v < top:
            return k
    return len(BANDS) - 1


def render_native(bbox, width=3072, block_deg=1.0, refresh=False):
    """Pinta desde los GeoTIFF nativos de EMODnet (~116 m).

    Los bloques ya estan en la cache de red porque fetch_grid los bajo para
    construir la rejilla de trabajo; aqui se releen sin pedir nada.

    El bucle interior se reduce a un indice porque todas las columnas de un
    bloque comparten el mismo mapa de filas: se precalcula `rbase[r]` una vez
    y cada pixel es un `data[rbase[r] + col]`. Muestrear por `value_at()` seria
    una llamada por pixel y multiplicaria el tiempo por diez.
    """
    from custody import bathymetry, net, tiff

    minlon, minlat, maxlon, maxlat = bbox
    # Alto derivado del ancho para que el pixel salga cuadrado EN MERCATOR,
    # que es como se va a dibujar.
    mx = math.radians(maxlon - minlon)
    my = _merc_y(maxlat) - _merc_y(minlat)
    height = int(round(width * my / mx))
    lats = _mercator_lats(minlat, maxlat, height)

    land = len(BANDS)
    px = bytearray([land]) * (width * height)
    hist = [0] * len(BANDS)
    blocks = 0

    for lo, hi, url in bathymetry.block_urls(bbox, block_deg):
        raw, _ = net.fetch(url, refresh=refresh, ext="tif", timeout=300)
        t = tiff.GeoTiff(raw)
        blocks += 1
        # Columnas de salida que caen en este bloque.
        c0 = max(0, int(math.ceil((lo - minlon) / (maxlon - minlon) * width)))
        c1 = min(width, int(math.floor((hi - minlon) / (maxlon - minlon) * width)))
        cols = []
        for c in range(c0, c1):
            lon = minlon + (c + 0.5) * (maxlon - minlon) / width
            col = int((lon - t.x0) / t.px)
            cols.append(col if 0 <= col < t.width else None)
        rbase = []
        for lat in lats:
            row = int((lat - t.y0) / t.py)
            rbase.append(row * t.width if 0 <= row < t.height else None)
        data = t.data
        for r in range(height):
            rb = rbase[r]
            if rb is None:
                continue
            out = r * width
            for k, col in enumerate(cols):
                if col is None:
                    continue
                v = data[rb + col]
                if v != v or v >= 0.0:        # NaN o tierra
                    continue
                b = _classify(-v)
                if b is None:
                    continue
                px[out + c0 + k] = b
                hist[b] += 1
        del t

    return _png(px, width, height), _stats(width, height, hist, bbox, blocks)


def _stats(nx, ny, hist, bbox, blocks=None):
    sea = sum(hist)
    st = {
        "nx": nx, "ny": ny,
        "lon0": bbox[0], "lat0": bbox[1], "lon1": bbox[2], "lat1": bbox[3],
        "projection": "EPSG:3857",
        "sea_cells": sea, "land_cells": nx * ny - sea,
        "bands": [{"max_m": None if top > 1e8 else top, "rgb": list(c),
                   "label": lab,
                   "share_pct": round(100.0 * n / sea, 1) if sea else 0.0}
                  for (top, c, lab), n in zip(BANDS, hist)],
        "anchor_limit_m": ANCHOR_LIMIT_M,
    }
    if blocks is not None:
        st["source_blocks"] = blocks
    return st


def render(grid, width=None):
    """Respaldo: pinta desde la rejilla de trabajo en vez de los GeoTIFF.

    Se usa si los bloques nativos no estan disponibles. Sale mas pobre (la
    rejilla es de 0,03 grados), pero cuadra igual con el mapa, porque las
    filas se espacian en Mercator como en la via buena.
    """
    get = (grid.__getitem__ if isinstance(grid, dict)
           else lambda k: getattr(grid, k))
    nx, ny, vals = get("nx"), get("ny"), get("vals")
    step, lon0, lat0 = get("step"), get("lon0"), get("lat0")
    lon1, lat1 = lon0 + (nx - 1) * step, lat0 + (ny - 1) * step

    w = width or nx
    mx = math.radians(lon1 - lon0)
    my = _merc_y(lat1) - _merc_y(lat0)
    h = int(round(w * my / mx))
    lats = _mercator_lats(lat0, lat1, h)

    land = len(BANDS)
    px = bytearray([land]) * (w * h)
    hist = [0] * len(BANDS)
    for r in range(h):
        j = int(round((lats[r] - lat0) / step))
        if not (0 <= j < ny):
            continue
        base, out = j * nx, r * w
        for c in range(w):
            i = int(round((lon0 + (c + 0.5) * (lon1 - lon0) / w - lon0) / step))
            if not (0 <= i < nx):
                continue
            b = _classify(vals[base + i])
            if b is None:
                continue
            px[out + c] = b
            hist[b] += 1
    return _png(px, w, h), _stats(w, h, hist, (lon0, lat0, lon1, lat1))


def verify(png_path, grid_path, n=6000):
    """Comprueba que el PNG cae donde dice, contra una fuente independiente.

    Decodifica el PNG propio (indexado, sin filtros por fila) y lo compara
    celda a celda con depth_grid.json, que se construyo por otro camino. Se
    mide DOS veces: con el mapeo de filas correcto y con el lineal-en-latitud
    que tenia el fallo. Si las dos puntuan igual, la comprobacion no sirve y
    hay que arreglarla antes de fiarse del resultado.

    Solo cuentan los puntos cuyo vecindario 3x3 en la rejilla es uniforme: a
    menos de 3 km de la costa las dos fuentes pueden discrepar legitimamente,
    porque el PNG es de ~292 m y la rejilla de 3 km.
    """
    blob = open(png_path, "rb").read()
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(blob):
        ln = struct.unpack(">I", blob[pos:pos + 4])[0]
        tag = blob[pos + 4:pos + 8]
        if tag == b"IHDR":
            w, h = struct.unpack(">II", blob[pos + 8:pos + 16])
        elif tag == b"IDAT":
            idat += blob[pos + 8:pos + 8 + ln]
        pos += 12 + ln
    raw = zlib.decompress(idat)
    stride = w + 1
    land = len(BANDS)

    g = json.load(open(grid_path))
    nx, ny, step, lon0, lat0 = g["nx"], g["ny"], g["step"], g["lon0"], g["lat0"]
    lat1 = lat0 + (ny - 1) * step
    lon1 = lon0 + (nx - 1) * step
    y0, y1 = _merc_y(lat0), _merc_y(lat1)

    def wet_at(lat, lon):
        i = int(round((lon - lon0) / step))
        j = int(round((lat - lat0) / step))
        if not (0 <= i < nx and 0 <= j < ny):
            return None
        v = g["vals"][j * nx + i]
        return v is not None and v > 0

    out = {}
    for mode in ("mercator", "linear-in-latitude"):
        ok = tot = coast = 0
        for k in range(1, n + 1):
            lat = lat0 + ((k * 0.6180339887) % 1.0) * (lat1 - lat0)
            lon = lon0 + ((k * 0.7548776662) % 1.0) * (lon1 - lon0)
            wet = wet_at(lat, lon)
            if wet is None:
                continue
            uni = True
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    o = wet_at(lat + dj * step, lon + di * step)
                    if o is None or o != wet:
                        uni = False
                        break
                if not uni:
                    break
            if not uni:
                coast += 1
                continue
            if mode == "mercator":
                r = int(round((y1 - _merc_y(lat)) / (y1 - y0) * h))
            else:
                r = int(round((lat1 - lat) / (lat1 - lat0) * h))
            c = int(round((lon - lon0) / (lon1 - lon0) * w))
            if not (0 <= r < h and 0 <= c < w):
                continue
            tot += 1
            if (raw[r * stride + 1 + c] != land) == wet:
                ok += 1
        out[mode] = {"samples": tot, "agree": ok,
                     "pct": round(100.0 * ok / tot, 2) if tot else 0.0,
                     "skipped_coastal": coast}
    return out


if __name__ == "__main__":
    import sys
    # Uso: -m custody.depthmap <png> [minlon minlat maxlon maxlat] [ancho]
    if sys.argv[1] == "--verify":
        print(json.dumps(verify(sys.argv[2], sys.argv[3])))
        raise SystemExit(0)
    dst = sys.argv[1]
    bbox = tuple(float(x) for x in sys.argv[2:6]) if len(sys.argv) > 5 \
        else (9.0, 53.5, 30.5, 66.0)
    width = int(sys.argv[6]) if len(sys.argv) > 6 else 3072
    blob, st = render_native(bbox, width=width)
    open(dst, "wb").write(blob)
    with open(dst.rsplit(".", 1)[0] + ".json", "w") as fh:
        json.dump(st, fh, indent=1)
    print("%s  %d x %d  %.0f kB  %d bloques  mar %d / tierra %d"
          % (dst, st["nx"], st["ny"], len(blob) / 1024.0, st["source_blocks"],
             st["sea_cells"], st["land_cells"]))
    for b in st["bands"]:
        print("   %-10s %5.1f%%" % (b["label"], b["share_pct"]))
