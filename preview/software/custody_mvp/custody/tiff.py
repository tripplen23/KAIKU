"""Lector mínimo de GeoTIFF float32 sin comprimir. Solo stdlib.

Alcance deliberado: lo que devuelve EMODnet Bathymetry WCS 2.0.1 con
`format=image/tiff` y nada más. Soporta big/little endian, 1 banda,
BitsPerSample=32, SampleFormat=3 (IEEE float), Compression=1 (ninguna),
organización por tiles o por strips, y georreferenciación por
ModelTransformationTag (34264) o por ModelTiepoint+PixelScale (33922/33550).

Cualquier otra combinación lanza NotImplementedError en lugar de devolver
números silenciosamente mal. No se escribe un lector general: se escribe el
lector del caso que está verificado.
"""
import array
import struct

TAG = {256: "width", 257: "height", 258: "bits", 259: "compression",
       273: "strip_offsets", 277: "samples", 278: "rows_per_strip",
       279: "strip_bytes", 322: "tile_w", 323: "tile_h", 324: "tile_offsets",
       325: "tile_bytes", 339: "sample_format", 33550: "pixel_scale",
       33922: "tiepoint", 34264: "transform"}

_TYPESZ = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
_TYPEFMT = {1: "B", 3: "H", 4: "I", 8: "h", 9: "i", 11: "f", 12: "d"}


class GeoTiff:
    def __init__(self, blob):
        self.b = blob
        if blob[:2] == b"II":
            self.e = "<"
        elif blob[:2] == b"MM":
            self.e = ">"
        else:
            raise NotImplementedError("no es TIFF")
        magic, ifd = struct.unpack_from(self.e + "HI", blob, 2)
        if magic != 42:
            raise NotImplementedError("BigTIFF no soportado")
        self.tags = self._read_ifd(ifd)

        g = self.tags
        self.width = int(g["width"][0])
        self.height = int(g["height"][0])
        if int(g.get("samples", [1])[0]) != 1:
            raise NotImplementedError("solo 1 banda")
        if int(g["bits"][0]) != 32 or int(g.get("sample_format", [1])[0]) != 3:
            raise NotImplementedError("solo float32 (bits=32, sample_format=3)")
        if int(g.get("compression", [1])[0]) != 1:
            raise NotImplementedError("solo sin comprimir")

        if "transform" in g:
            t = g["transform"]
            self.px, self.py = float(t[0]), float(t[5])   # py negativo
            self.x0, self.y0 = float(t[3]), float(t[7])
        elif "tiepoint" in g and "pixel_scale" in g:
            tp, sc = g["tiepoint"], g["pixel_scale"]
            self.x0, self.y0 = float(tp[3]), float(tp[4])
            self.px, self.py = float(sc[0]), -float(sc[1])
        else:
            raise NotImplementedError("sin georreferenciación reconocible")

        self.data = self._read_pixels()

    def _read_ifd(self, off):
        n, = struct.unpack_from(self.e + "H", self.b, off)
        out = {}
        for i in range(n):
            p = off + 2 + i * 12
            tag, typ, cnt = struct.unpack_from(self.e + "HHI", self.b, p)
            size = _TYPESZ.get(typ, 0) * cnt
            vp = p + 8
            if size > 4:
                vp, = struct.unpack_from(self.e + "I", self.b, p + 8)
            fmt = _TYPEFMT.get(typ)
            if fmt is None:
                continue
            vals = struct.unpack_from(self.e + str(cnt) + fmt, self.b, vp)
            out[TAG.get(tag, tag)] = vals
        return out

    def _floats(self, off, nbytes):
        a = array.array("f")
        a.frombytes(self.b[off:off + nbytes])
        if (self.e == "<") != (struct.pack("=H", 1) == b"\x01\x00"):
            a.byteswap()
        return a

    def _read_pixels(self):
        g = self.tags
        out = array.array("f", [float("nan")]) * (self.width * self.height)
        if "tile_offsets" in g:
            tw, th = int(g["tile_w"][0]), int(g["tile_h"][0])
            across = (self.width + tw - 1) // tw
            for i, (off, nb) in enumerate(zip(g["tile_offsets"], g["tile_bytes"])):
                tile = self._floats(int(off), int(nb))
                tx, ty = (i % across) * tw, (i // across) * th
                for r in range(th):
                    y = ty + r
                    if y >= self.height:
                        break
                    n = min(tw, self.width - tx)
                    base = y * self.width + tx
                    out[base:base + n] = tile[r * tw:r * tw + n]
        elif "strip_offsets" in g:
            rps = int(g.get("rows_per_strip", [self.height])[0])
            for i, (off, nb) in enumerate(zip(g["strip_offsets"], g["strip_bytes"])):
                strip = self._floats(int(off), int(nb))
                y0 = i * rps
                rows = min(rps, self.height - y0)
                out[y0 * self.width:(y0 + rows) * self.width] = strip[:rows * self.width]
        else:
            raise NotImplementedError("ni tiles ni strips")
        return out

    def value_at(self, lon, lat):
        """Vecino más próximo. None fuera del raster."""
        col = int((lon - self.x0) / self.px)
        row = int((lat - self.y0) / self.py)
        if not (0 <= col < self.width and 0 <= row < self.height):
            return None
        v = self.data[row * self.width + col]
        return None if v != v else v   # NaN
