"""Fusionar un almacen AIS dentro de otro. Idempotente, sin parar la grabadora.

POR QUE EXISTE.

La grabadora ha vivido en dos sitios. El 2026-11-13 se reinicio apuntando a
`~/ais_data` mientras el almacen configurado seguia en Dropbox, y durante 4,6 h
escribio donde la aplicacion no miraba. Que el lector sepa leer los dos es un
parche: lo que el sistema necesita es UN almacen y un sitio donde se declara
cual es (config/custody.toml, clave `paths.record`).

POR QUE NO HACE FALTA PARAR LA GRABADORA.

El formato ya es el correcto para esto. De store.py:

    «Each write batch is an INDEPENDENT gzip member appended to the file
     (RFC 1952 allows member concatenation) ... resume is "open in append
     mode". No rewrite, no compaction.»

O sea que fusionar es la operacion nativa del almacen, no una excepcion: se
anaden miembros al final. Nada se reescribe, asi que un lote a medio escribir
en el origen no se corrompe -- simplemente no se copia todavia, y la siguiente
pasada lo recoge.

IDEMPOTENTE A PROPOSITO. Se compara registro a registro por su identidad
natural, no por fichero ni por lote, asi que se puede ejecutar las veces que
haga falta: dos veces seguidas, o despues de que la grabadora haya escrito
otro rato en el origen. La segunda pasada copia cero.

    locations  (mmsi, timestampExternal)
    vessels    (mmsi, timestamp)
    polllog    (stream, rx_ms, seq)

NO BORRA EL ORIGEN. Es observacion primaria: nadie puede volver a grabar el
13 de noviembre de 2026. Que se borre lo decide una persona, mirando antes el
recuento que imprime esto.

    python3 merge_store.py --from ~/ais_data             # simulacro
    python3 merge_store.py --from ~/ais_data --apply
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from datetime import datetime, timezone

import store

KEYS = {
    "locations": lambda r: (r.get("mmsi"), r.get("timestampExternal")),
    "mqtt_locations": lambda r: (r.get("mmsi"), r.get("time")),
    "vessels": lambda r: (r.get("mmsi"), r.get("timestamp")),
    "mqtt_metadata": lambda r: (r.get("mmsi"), r.get("timestamp")),
    "polllog": lambda r: (r.get("stream"), r.get("rx_ms"), r.get("seq")),
}


def _read(path):
    out = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _day_files(root):
    """(stream, fecha, ruta) de cada fichero diario del almacen."""
    base = os.path.join(root, "raw")
    out = []
    if not os.path.isdir(base):
        return out
    for stream in sorted(os.listdir(base)):
        d = os.path.join(base, stream)
        if not os.path.isdir(d):
            continue
        for dirpath, _, names in os.walk(d):
            for n in sorted(names):
                if n.endswith(".ndjson.gz"):
                    date = n.rsplit("-", 3)[-3:]
                    out.append((stream, "-".join(n[:-10].split("-")[-3:]),
                                os.path.join(dirpath, n)))
    return sorted(out)


def merge(src, dst, apply=False, log=print):
    if os.path.realpath(src) == os.path.realpath(dst):
        raise SystemExit("origen y destino son el mismo almacen")
    if not os.path.isdir(os.path.join(src, "raw")):
        raise SystemExit("no hay raw/ en %s" % src)

    files = _day_files(src)
    log("origen  %s  %d ficheros" % (src, len(files)))
    log("destino %s" % dst)
    log("")
    tot_new = tot_dup = 0
    for stream, date, path in files:
        key = KEYS.get(stream)
        if key is None:
            log("  %-16s %s  SALTADO (stream desconocido)" % (stream, date))
            continue
        recs = _read(path)
        dpath = os.path.join(dst, "raw", stream, date[:4], date[5:7],
                             "%s-%s.ndjson.gz" % (stream, date))
        have = set()
        if os.path.exists(dpath):
            have = {key(r) for r in _read(dpath)}
        fresh, seen = [], set()
        for r in recs:
            k = key(r)
            if k in have or k in seen:
                continue
            seen.add(k)
            fresh.append(r)
        dup = len(recs) - len(fresh)
        tot_new += len(fresh)
        tot_dup += dup
        log("  %-16s %s  %7d en origen  %7d ya estaban  %7d a copiar"
            % (stream, date, len(recs), dup, len(fresh)))
        if apply and fresh:
            dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            # El escritor del propio almacen: mismo formato, mismo fsync,
            # mismo sha256 en el registro. No se reimplementa aqui.
            store.append_batch(dst, stream, dt, fresh)
    log("")
    log("%s  %d registros nuevos, %d ya presentes"
        % ("COPIADO:" if apply else "SIMULACRO:", tot_new, tot_dup))
    if not apply and tot_new:
        log("Vuelve a lanzarlo con --apply para escribirlos.")
    return tot_new


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from", dest="src", required=True, help="almacen de origen")
    ap.add_argument("--to", dest="dst", default=None,
                    help="destino; por defecto el configurado en custody.toml")
    ap.add_argument("--apply", action="store_true", help="escribir de verdad")
    args = ap.parse_args(argv)

    dst = args.dst
    if dst is None:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "custody_mvp"))
        try:
            from custody import paths as _paths
            dst = _paths.record()
        except Exception as exc:
            raise SystemExit("sin --to y no puedo leer la configuracion: %s" % exc)
    if not dst:
        raise SystemExit("no hay almacen destino configurado")
    return 0 if merge(os.path.expanduser(args.src), os.path.expanduser(dst),
                      apply=args.apply) >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
