"""Geodesia mínima para el AOI del golfo de Finlandia. Solo stdlib.

Proyección local equirectangular centrada en LAT0. Error de distancia < 0,4 %
dentro de 59-61 N / 19-31 E frente a Vincenty; suficiente para umbrales
expresados en NM. Toda distancia en metros salvo que el nombre diga otra cosa.
"""
import math

LAT0 = 60.0
M_PER_DEG_LAT = 111_132.0
NM = 1852.0


def m_per_deg_lon(lat=LAT0):
    return 111_320.0 * math.cos(math.radians(lat))


def to_xy(lon, lat, lon0=25.0, lat0=LAT0):
    return ((lon - lon0) * m_per_deg_lon(lat0), (lat - lat0) * M_PER_DEG_LAT)


def haversine_m(lon1, lat1, lon2, lat2):
    r = 6_371_008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def angle_diff_deg(a, b):
    """Diferencia angular con signo mínimo en [0, 180]."""
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def _seg_dist_xy(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / L2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def polyline_length_m(coords):
    return sum(haversine_m(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
               for i in range(len(coords) - 1))


class SegmentIndex:
    """Índice uniforme de segmentos para consulta de distancia mínima.

    Rejilla de CELL grados. Cada segmento se registra en todas las celdas que
    toca su bbox. La consulta mira la celda del punto y los 8 vecinos, lo que
    acota el radio fiable a ~CELL*111 km; por encima devuelve None.
    """
    CELL = 0.05

    def __init__(self):
        self.cells = {}
        self.segs = []

    def add_polyline(self, coords, payload):
        for i in range(len(coords) - 1):
            a, b = coords[i], coords[i + 1]
            idx = len(self.segs)
            self.segs.append((a[0], a[1], b[0], b[1], payload))
            lo = (min(a[0], b[0]), min(a[1], b[1]))
            hi = (max(a[0], b[0]), max(a[1], b[1]))
            for cx in range(int(lo[0] / self.CELL), int(hi[0] / self.CELL) + 1):
                for cy in range(int(lo[1] / self.CELL), int(hi[1] / self.CELL) + 1):
                    self.cells.setdefault((cx, cy), []).append(idx)

    def nearest(self, lon, lat, max_rings=2):
        """(distancia_m, payload) al segmento más próximo, o (None, None)."""
        cx, cy = int(lon / self.CELL), int(lat / self.CELL)
        best, bestp = None, None
        for ring in range(max_rings + 1):
            cand = set()
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    if max(abs(dx), abs(dy)) != ring:
                        continue
                    cand.update(self.cells.get((cx + dx, cy + dy), ()))
            if cand:
                px, py = to_xy(lon, lat)
                for i in cand:
                    ax, ay, bx, by, payload = self.segs[i]
                    axp, ayp = to_xy(ax, ay)
                    bxp, byp = to_xy(bx, by)
                    d = _seg_dist_xy(px, py, axp, ayp, bxp, byp)
                    if best is None or d < best:
                        best, bestp = d, payload
            if best is not None and best <= ring * self.CELL * M_PER_DEG_LAT:
                break
        return best, bestp


def point_in_ring(lon, lat, ring):
    """Ray casting. ring = [(lon,lat), ...] cerrado o no."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > lat) != (y2 > lat):
            xint = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < xint:
                inside = not inside
    return inside


class PolygonMask:
    """Máscara de polígonos con prefiltro por bbox. Para puertos/fondeaderos."""

    def __init__(self):
        self.polys = []  # (minlon, minlat, maxlon, maxlat, ring, name)

    def add(self, ring, name):
        if len(ring) < 3:
            return
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        self.polys.append((min(xs), min(ys), max(xs), max(ys), ring, name))

    def add_circle(self, lon, lat, radius_m, name, n=16):
        dlat = radius_m / M_PER_DEG_LAT
        dlon = radius_m / m_per_deg_lon(lat)
        ring = [(lon + dlon * math.cos(2 * math.pi * k / n),
                 lat + dlat * math.sin(2 * math.pi * k / n)) for k in range(n)]
        self.add(ring, name)

    def hit(self, lon, lat):
        for mnx, mny, mxx, mxy, ring, name in self.polys:
            if mnx <= lon <= mxx and mny <= lat <= mxy and point_in_ring(lon, lat, ring):
                return name
        return None

    def __len__(self):
        return len(self.polys)


def clip_polyline(coords, bbox):
    """Recorta una polilínea a bbox=(minlon,minlat,maxlon,maxlat).

    Devuelve lista de polilíneas. Cohen-Sutherland por segmento, con el punto
    de cruce interpolado: si no se interpola, la línea aparece cortada a varios
    km del borde y el corredor "termina" donde no termina.
    """
    mnx, mny, mxx, mxy = bbox

    def code(p):
        c = 0
        if p[0] < mnx:
            c |= 1
        elif p[0] > mxx:
            c |= 2
        if p[1] < mny:
            c |= 4
        elif p[1] > mxy:
            c |= 8
        return c

    out, cur = [], []
    for i in range(len(coords) - 1):
        a = (coords[i][0], coords[i][1])
        b = (coords[i + 1][0], coords[i + 1][1])
        ax, ay, bx, by = a[0], a[1], b[0], b[1]
        ca, cb = code(a), code(b)
        accept = False
        while True:
            if not (ca | cb):
                accept = True
                break
            if ca & cb:
                break
            c = ca or cb
            if c & 8:
                x = ax + (bx - ax) * (mxy - ay) / (by - ay)
                y = mxy
            elif c & 4:
                x = ax + (bx - ax) * (mny - ay) / (by - ay)
                y = mny
            elif c & 2:
                y = ay + (by - ay) * (mxx - ax) / (bx - ax)
                x = mxx
            else:
                y = ay + (by - ay) * (mnx - ax) / (bx - ax)
                x = mnx
            if c == ca:
                ax, ay = x, y
                ca = code((ax, ay))
            else:
                bx, by = x, y
                cb = code((bx, by))
        if not accept:
            if cur:
                out.append(cur)
                cur = []
            continue
        if not cur:
            cur = [(ax, ay)]
        elif abs(cur[-1][0] - ax) > 1e-9 or abs(cur[-1][1] - ay) > 1e-9:
            out.append(cur)
            cur = [(ax, ay)]
        cur.append((bx, by))
    if cur:
        out.append(cur)
    return [p for p in out if len(p) >= 2]
