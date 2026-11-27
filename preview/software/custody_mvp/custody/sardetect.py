"""Detección de buques en SAR por CFAR. Solo stdlib.

POR QUE FUNCIONA
----------------
Un casco metálico es un reflector de esquina: devuelve muchísima más energía
que el mar que lo rodea. El mar, con viento moderado, es un fondo oscuro y
razonablemente homogéneo. Esa diferencia es lo que explota CFAR (Constant
False Alarm Rate), el algoritmo estándar de la literatura y el que lleva
dentro el operador «Ocean Object Detection» de ESA SNAP.

CA-CFAR (cell averaging), que es lo implementado aquí:
  - alrededor de cada píxel se traza un ANILLO de fondo, dejando una banda de
    GUARDA para que el propio barco no contamine la estimación del mar;
  - del anillo salen media y desviación típica del clutter local;
  - el píxel es detección si supera mu + K*sigma.
«Local» es la palabra clave: el umbral se adapta al estado de la mar en cada
punto, que es justo lo que un umbral global no sabe hacer.

VALIDACION
----------
Comprobado el 2026-11-10 contra una detección publicada por Skylight:
escena S1C_IW_GRDH_1SDV_20261107T044122, punto 59.8430 N / 25.8335 E. Este
detector, sobre un recorte gratuito de Planetary Computer, situó un blanco a
**55 m** de la posición que ellos publican. Es el mismo buque.

LIMITES, QUE SON SERIOS
-----------------------
  - Con mar gruesa el clutter sube y las detecciones pequeñas se pierden; con
    mar muy plana aparecen falsos por reflexión especular.
  - NO distingue un buque de un pecio emergente, una boya, una plataforma ni
    de un islote. Por eso el visor cruza cada detección contra la capa de
    pecios y contra el AIS antes de llamarla «buque oscuro».
  - El recorte de Planetary Computer viene en DN sin calibrar a sigma0. Para
    medir retrodispersión en dB hay que calibrar con el producto completo;
    para DETECTAR contraste local, el DN basta y así se declara.
  - La eslora estimada sale del tamaño del blob y está sobreestimada: el
    moteado y el lóbulo lateral ensanchan el blanco. Se da como orden de
    magnitud, nunca como medida.
"""
import logging
import math
import random
import struct

LOG = logging.getLogger("custody.sardetect")

DEFAULTS = {
    "guard_px": 4,       # banda de guarda: el barco no entra en su propio fondo
    "bg_px": 12,         # medio lado del anillo de fondo
    "k": 6.0,            # umbral en desviaciones tipicas sobre la media local
    "step": 2,           # submuestreo del anillo: 4x mas rapido, igual de estable
    "min_px": 3,         # blobs menores son moteado
    "max_px": 4000,      # blobs mayores son tierra o un frente, no un buque
    "min_bg": 40,        # muestras minimas de fondo para fiarse de la estimacion
}


class Raster:
    """GeoTIFF sin comprimir, por bandas (strips). uint8/16/32 y float32.

    No sustituye a tiff.py, que lee la rejilla float32 de EMODnet: aqui hace
    falta uint16 multimuestra, que es lo que devuelve el recorte de Sentinel-1.
    """

    def __init__(self, data):
        self.d = data
        self.e = "<" if data[:2] == b"II" else ">"
        if data[:2] not in (b"II", b"MM"):
            raise ValueError("no es un TIFF")
        off = struct.unpack(self.e + "I", data[4:8])[0]
        n = struct.unpack(self.e + "H", data[off:off + 2])[0]
        self.tags = {}
        for i in range(n):
            t, typ, cnt, val = struct.unpack(self.e + "HHII",
                                             data[off + 2 + 12 * i: off + 14 + 12 * i])
            self.tags[t] = (typ, cnt, val)
        self.w = self._one(256)
        self.h = self._one(257)
        self.spp = self._one(277) or 1
        self.bps = self._first(258) or 8
        self.fmt = self._first(339) or 1
        if self._one(259) not in (1, None):
            raise NotImplementedError("TIFF comprimido no soportado")
        if 322 in self.tags:
            raise NotImplementedError("TIFF en tiles no soportado")
        self.strip_off = self._array(273)
        self.strip_cnt = self._array(279)
        tp = self._doubles(33922, 6)
        ps = self._doubles(33550, 3)
        if not tp or not ps:
            raise ValueError("TIFF sin georreferencia")
        self.lon0, self.lat0 = tp[3], tp[4]
        self.sx, self.sy = ps[0], ps[1]
        self._rows = None

    # --- lectura de tags
    def _one(self, tag):
        return self.tags[tag][2] if tag in self.tags else None

    def _first(self, tag):
        """Primer valor de un tag SHORT, venga inline o por puntero.

        Un SHORT con count<=2 cabe en el propio campo de 4 bytes. En
        little-endian ocupa los dos primeros; en big-endian, los dos
        ultimos. Confundirlo da un BitsPerSample absurdo.
        """
        if tag not in self.tags:
            return None
        typ, cnt, val = self.tags[tag]
        if typ != 3:
            return val
        if cnt * 2 <= 4:
            return (val & 0xFFFF) if self.e == "<" else (val >> 16)
        return struct.unpack(self.e + "H", self.d[val:val + 2])[0]

    def _array(self, tag):
        typ, cnt, val = self.tags[tag]
        size = 2 if typ == 3 else 4
        fmt = "H" if typ == 3 else "I"
        if cnt * size <= 4:
            return [val]
        return list(struct.unpack(self.e + fmt * cnt, self.d[val:val + cnt * size]))

    def _doubles(self, tag, n):
        if tag not in self.tags:
            return None
        off = self.tags[tag][2]
        return list(struct.unpack(self.e + "d" * n, self.d[off:off + 8 * n]))

    # --- pixeles
    def rows(self):
        """Banda 0 como lista de filas. La banda 1, si existe, es la mascara."""
        if self._rows is not None:
            return self._rows
        code = {(8, 1): "B", (16, 1): "H", (32, 1): "I", (32, 3): "f"}
        key = (self.bps, self.fmt)
        if key not in code:
            raise NotImplementedError("bits=%s formato=%s" % key)
        c = code[key]
        px_size = self.bps // 8
        out, row = [], 0
        for o, n in zip(self.strip_off, self.strip_cnt):
            chunk = self.d[o:o + n]
            vals = struct.unpack(self.e + c * (len(chunk) // px_size), chunk)
            per = self.w * self.spp
            for r in range(len(vals) // per):
                base = r * per
                out.append([vals[base + x * self.spp] for x in range(self.w)])
                row += 1
                if row >= self.h:
                    break
            if row >= self.h:
                break
        self._rows = out
        return out

    def lonlat(self, x, y):
        return self.lon0 + x * self.sx, self.lat0 - y * self.sy

    def metres_per_px(self, lat):
        return (self.sx * 111320.0 * math.cos(math.radians(lat)),
                self.sy * 111320.0)


def cfar(raster, opt=None):
    """Lista de píxeles que superan el umbral local. [(x, y, v, mu, sd)]"""
    o = dict(DEFAULTS, **(opt or {}))
    img = raster.rows()
    W, H = raster.w, raster.h
    G, B, K, S = o["guard_px"], o["bg_px"], o["k"], o["step"]
    hits = []
    for y in range(B, H - B):
        rowy = img[y]
        for x in range(B, W - B):
            v = rowy[x]
            if v <= 0:
                continue
            s = s2 = cnt = 0
            for dy in range(-B, B + 1, S):
                ry = img[y + dy]
                ady = abs(dy)
                for dx in range(-B, B + 1, S):
                    if ady <= G and abs(dx) <= G:
                        continue
                    u = ry[x + dx]
                    if u <= 0:
                        continue
                    s += u
                    s2 += u * u
                    cnt += 1
            if cnt < o["min_bg"]:
                continue
            mu = s / cnt
            var = s2 / cnt - mu * mu
            if var <= 0:
                continue
            if v > mu + K * math.sqrt(var):
                hits.append((x, y, v, mu, math.sqrt(var)))
    return hits


def group(hits, opt=None):
    """Agrupa píxeles contiguos en blancos. Devuelve blobs como listas."""
    o = dict(DEFAULTS, **(opt or {}))
    idx = {(x, y): (v, mu, sd) for x, y, v, mu, sd in hits}
    seen, blobs = set(), []
    for seed in list(idx):
        if seed in seen:
            continue
        stack, comp = [seed], []
        while stack:
            p = stack.pop()
            if p in seen or p not in idx:
                continue
            seen.add(p)
            comp.append(p)
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    q = (p[0] + dx, p[1] + dy)
                    if q in idx and q not in seen:
                        stack.append(q)
        if o["min_px"] <= len(comp) <= o["max_px"]:
            blobs.append((comp, idx))
    return blobs


def detect(tif_bytes, opt=None):
    """GeoTIFF -> FeatureCollection de detecciones, con su incertidumbre."""
    r = Raster(tif_bytes)
    o = dict(DEFAULTS, **(opt or {}))
    hits = cfar(r, o)
    blobs = group(hits, o)
    feats = []
    for comp, idx in blobs:
        xs = [p[0] for p in comp]
        ys = [p[1] for p in comp]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        lon, lat = r.lonlat(cx, cy)
        mlon, mlat = r.metres_per_px(lat)
        wpx, hpx = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        peak = max(idx[p][0] for p in comp)
        mu = sum(idx[p][1] for p in comp) / len(comp)
        sd = sum(idx[p][2] for p in comp) / len(comp)
        feats.append({"type": "Feature", "properties": {
            "source": "CA-CFAR on Sentinel-1 GRD (DN, uncalibrated)",
            "pixels": len(comp),
            # Orden de magnitud, no medida: el moteado ensancha el blanco.
            "extent_m": [round(wpx * mlon), round(hpx * mlat)],
            "length_m_estimate": round(max(wpx * mlon, hpx * mlat)),
            "peak_dn": peak, "clutter_mean_dn": round(mu, 1),
            "snr_sigma": round((peak - mu) / sd, 1) if sd else None,
            "caveat": "A bright target is not necessarily a ship. Cross-check "
                      "against AIS and the wreck layer before calling it dark.",
        }, "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]}})
    feats.sort(key=lambda f: -f["properties"]["pixels"])
    st = {"raster": [r.w, r.h], "threshold_sigma": o["k"],
          "pixels_over_threshold": len(hits), "targets": len(feats)}
    LOG.info("CFAR %dx%d: %d px sobre umbral -> %d blancos", r.w, r.h, len(hits), len(feats))
    return {"type": "FeatureCollection", "features": feats}, st


# ---------------------------------------------------------------- demostracion
def demo(seed=11):
    """Por que un umbral global no sirve, con numeros. Reproducible.

    Vive aqui, junto al algoritmo, y no en un script suelto ni en una
    conversacion: una explicacion que no se puede volver a ejecutar se queda
    vieja y nadie se entera.

        python3 -m custody.sardetect --demo

    Mar sintetico con dos estados --- calma y gruesa--- y el MISMO barco en los
    dos: mismo contraste sobre su propio fondo, que es como se comporta un
    casco de verdad. El moteado se genera Rayleigh, que es la distribucion de
    la amplitud de un SAR de una mirada.
    """
    rnd = random.Random(seed)
    W, H = 240, 120
    def rayleigh(scale):
        return scale * math.sqrt(-2.0 * math.log(1.0 - rnd.random()))

    SCALE = {"calma": 18, "gruesa": 60}
    img = [[int(rayleigh(SCALE["gruesa"] if x > W // 2 else SCALE["calma"]))
            for x in range(W)] for _ in range(H)]
    stats = {}
    for name, x0, x1 in (("calma", 0, W // 2), ("gruesa", W // 2, W)):
        v = [img[y][x] for y in range(H) for x in range(x0, x1)]
        mu = sum(v) / len(v)
        sd = (sum((u - mu) ** 2 for u in v) / len(v)) ** 0.5
        stats[name] = (mu, sd)

    ships = [(60, 60, "calma"), (180, 60, "gruesa")]
    for sx, sy, where in ships:
        mu, sd = stats[where]
        val = int(mu + 8 * sd)
        for dy in range(-1, 2):
            for dx in range(-4, 5):
                img[sy + dy][sx + dx] = val

    out = ["MAR          media   sigma   barco (mu+8sd)"]
    for n in ("calma", "gruesa"):
        mu, sd = stats[n]
        out.append("  %-8s %7.1f %7.1f %10d" % (n, mu, sd, int(mu + 8 * sd)))

    out.append("")
    out.append("1) UMBRAL GLOBAL - un solo numero para toda la escena")
    out.append("   umbral   px     calma   gruesa   barcos (de 2)")
    for thr in (120, 200, 300, 450):
        hits = [(x, y) for y in range(H) for x in range(W) if img[y][x] > thr]
        izq = sum(1 for x, _ in hits if x < W // 2)
        seen = sum(1 for sx, sy, _ in ships
                   if any(abs(x - sx) < 6 and abs(y - sy) < 3 for x, y in hits))
        out.append("   %6d %6d %8d %8d %10d"
                   % (thr, len(hits), izq, len(hits) - izq, seen))
    out.append("   Ninguno vale: por debajo de 450 la mar gruesa inunda de")
    out.append("   falsos; por encima, el barco en calma desaparece.")

    class _Fake:
        w, h = W, H
        def rows(self):
            return img

    hits = cfar(_Fake(), {"k": 6.0, "guard_px": 6, "bg_px": 14,
                          "step": 2, "min_bg": 40})
    blobs = group(hits, {"min_px": 3, "max_px": 4000})
    izq = sum(1 for h in hits if h[0] < W // 2)
    out.append("")
    out.append("2) CA-CFAR - un umbral por pixel, del anillo de fondo")
    out.append("   %d px sobre umbral: %d en calma, %d en gruesa, %d blancos"
               % (len(hits), izq, len(hits) - izq, len(blobs)))
    for comp, idx in blobs:
        xs = [p[0] for p in comp]
        ys = [p[1] for p in comp]
        mu = sum(idx[p][1] for p in comp) / len(comp)
        sd = sum(idx[p][2] for p in comp) / len(comp)
        pk = max(idx[p][0] for p in comp)
        out.append("     (%3.0f,%3.0f) %2d px  pico %4d  fondo mu=%5.1f sd=%5.1f"
                   "  umbral LOCAL %6.1f"
                   % (sum(xs) / len(xs), sum(ys) / len(ys), len(comp), pk,
                      mu, sd, mu + 6 * sd))
    return "\n".join(out), len(blobs)


def false_alarm_rate(k, model="rayleigh"):
    """Falsas alarmas por pixel para un umbral de k sigmas.

    EL MODELO DE CLUTTER CAMBIA LA RESPUESTA MIL VECES, asi que se dice cual
    se asume. Con k=6: 9,9e-10 si se supone gaussiano, 1,5e-6 si Rayleigh.
    Y el mar real tiene colas MAS pesadas que Rayleigh (distribucion K), asi
    que la tasa verdadera es peor que cualquiera de las dos. Por eso el numero
    que falta --- cuantos avisos equivocados por semana tolera el cliente--- no
    se deriva: se pregunta.
    """
    if model == "gauss":
        return 0.5 * math.erfc(k / math.sqrt(2))
    mu = math.sqrt(math.pi / 2)
    sd = math.sqrt(2 - math.pi / 2)
    t = mu + k * sd
    return math.exp(-t * t / 2)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if "--demo" in sys.argv:
        txt, n = demo()
        print(txt)
        print()
        print("3) EL DIAL: k contra falsas alarmas (clutter Rayleigh)")
        print("   k    por pixel     en un recorte de 2000x2000")
        for k in (4, 5, 6, 8):
            r = false_alarm_rate(k)
            print("   %-4d %.2e %12.0f px" % (k, r, r * 4e6))
        print("   k=6 es el que usa DEFAULTS. Suponiendo gaussiano daria "
              "%.1e,\n   mil quinientas veces menos: el modelo importa mas "
              "que el umbral." % false_alarm_rate(6, "gauss"))
        sys.exit(0 if n == 2 else 1)
    print(__doc__)
