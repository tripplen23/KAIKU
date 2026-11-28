"""Rutas y parametros del proyecto, en un solo sitio.

Antes cada modulo construia las suyas con os.path.join sobre __file__, lo que
significa que para mover la cache a otro disco habia que editar cuatro
ficheros y acordarse de los cuatro.

Orden de precedencia, de mas a menos fuerte:

    1. variable de entorno   CUSTODY_PATHS_CACHE=/mnt/ssd/cache
    2. config/custody.toml
    3. los valores por defecto de abajo

El TOML se lee con tomllib (estandar desde Python 3.11). Si no esta el
fichero, el proyecto sigue funcionando con los defaults: la configuracion
es una comodidad, no un requisito de arranque.
"""
import os
import time

try:
    import tomllib
except ImportError:                                   # py < 3.11
    tomllib = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config", "custody.toml")

DEFAULTS = {
    "aoi": {"bbox": [9.0, 53.5, 30.5, 66.0], "name": "Baltic Sea"},
    "paths": {"cache": "cache", "data": "viewer/data",
              "record": "~/ais_data", "secrets": "secrets.env",
              "weights": "custody/weights/ship_motion_mlp.json",
              "anchor_weights": "custody/weights/anchor_drag_tier2.json",
              "record_extra": [], "record_watch": []},
    "cache": {"ttl_stac": 21600, "ttl_geo": 2592000, "ttl_tile": 0},
    "build": {"depth_step": 0.03, "viewer_depth_step": 0.06,
              "isobaths_m": [20.0, 50.0, 80.0, 100.0]},
}


def _load():
    cfg = {k: dict(v) for k, v in DEFAULTS.items()}
    if tomllib and os.path.exists(CONFIG):
        with open(CONFIG, "rb") as fh:
            for sec, vals in (tomllib.load(fh) or {}).items():
                cfg.setdefault(sec, {}).update(vals)
    for sec in cfg:
        for key in list(cfg[sec]):
            env = os.environ.get("CUSTODY_%s_%s" % (sec.upper(), key.upper()))
            if not env:
                continue
            cur = cfg[sec][key]
            if isinstance(cur, bool):
                cfg[sec][key] = env.lower() in ("1", "true", "yes")
            elif isinstance(cur, (int, float)) and not isinstance(cur, bool):
                cfg[sec][key] = type(cur)(env)
            elif isinstance(cur, list):
                cfg[sec][key] = [x.strip() for x in env.split(",") if x.strip()]
            else:
                cfg[sec][key] = env
    return cfg


CFG = _load()


def abspath(p):
    """Absoluta. `~` se expande; lo relativo cuelga de la raiz del proyecto."""
    p = os.path.expanduser(str(p))
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(ROOT, p))


def cache(*parts):
    """Funcion pura de una fuente externa. Borrarla cuesta tiempo, no datos."""
    return os.path.join(abspath(CFG["paths"]["cache"]), *parts)


def data(*parts):
    """Salida del build: funcion de (cache + codigo + config). Reconstruible."""
    return os.path.join(abspath(CFG["paths"]["data"]), *parts)


def records():
    """Los almacenes DECLARADOS que existen. Normalmente uno.

    UN SISTEMA, UN ALMACEN, Y UN SITIO DONDE SE DICE CUAL.

    `record` en config/custody.toml es la unica respuesta a «donde estan los
    datos». `record_extra` existe para un caso concreto --montar un archivo
    historico de solo lectura junto al actual-- y por defecto esta vacia.

    La version anterior tenia `record_fallbacks`: una lista de sitios donde
    BUSCAR si el principal no estaba. Eso parece prudente y no lo es, porque
    convierte un error de configuracion en silencio. Primero devolvia el
    primero que existiera e ignoraba el resto, y asi se perdieron 4,6 h de
    vista (2026-11-13: la grabadora reiniciada contra `~/ais_data` mientras
    el principal seguia en Dropbox). Leerlos todos arreglo la ceguera pero
    dejo una aplicacion que lee de dos sitios sin que nadie lo haya pedido.

    Ahora los respaldos no se leen: se VIGILAN. Ver stray_records().
    """
    out, seen = [], set()
    cands = [CFG["paths"]["record"]] + list(CFG["paths"].get("record_extra") or [])
    env = os.environ.get("AIS_DATA_ROOT")
    if env:
        cands.insert(0, env)
    for c in cands:
        a = abspath(c)
        if a in seen or not os.path.isdir(a):
            continue
        seen.add(a)
        out.append(a)
    return out


def record():
    """El almacen. Para escribir y para nombrarlo."""
    r = records()
    return r[0] if r else None


def has_data(root):
    """(ficheros diarios, mtime del mas reciente). Un directorio vacio no es
    un almacen, y uno que nadie toca desde hace dias no es lo mismo que uno
    donde una grabadora esta escribiendo ahora: lo primero se limpia, lo
    segundo se arregla."""
    base = os.path.join(root, "raw", "locations")
    if not os.path.isdir(base):
        return 0, 0
    n, newest = 0, 0
    for dirpath, _, names in os.walk(base):
        for x in names:
            if not x.endswith(".ndjson.gz"):
                continue
            n += 1
            try:
                newest = max(newest, os.path.getmtime(os.path.join(dirpath, x)))
            except OSError:
                pass
    return n, newest


def stray_records():
    """Grabacion que esta donde NO deberia, con lo que hay que hacer con ella.

    Esto es la otra mitad de «un almacen». Declarar uno solo no impide que
    algo escriba en otro sitio --- una grabadora con el `--root` viejo, una
    copia a medio mover--- y la version anterior de esto se tragaba el dato
    en silencio porque los respaldos se leian como si tal cosa.

    Aqui NO se leen. Se mira si tienen contenido y se dice, para que la
    aplicacion pueda avisar en vez de disimular. Lo que hay que hacer con
    ellos es siempre lo mismo:

        python3 ais_recorder/merge_store.py --from <ruta> --apply

    y despues borrarlos a mano, nunca automaticamente: es observacion
    primaria y nadie puede volver a grabar ese dia.
    """
    known = {abspath(c) for c in
             [CFG["paths"]["record"]] + list(CFG["paths"].get("record_extra") or [])}
    out = []
    for c in list(CFG["paths"].get("record_watch") or []):
        a = abspath(c)
        if a in known or not os.path.isdir(a):
            continue
        n, newest = has_data(a)
        if n:
            out.append({"path": a, "day_files": n,
                        "newest_ms": int(newest * 1000),
                        # Si algo sigue escribiendo ahi, no basta con
                        # fusionar: hay que apuntar la grabadora al almacen
                        # declarado, o manana vuelve a pasar.
                        "active": (time.time() - newest) < 900})
    return out


def secrets():
    return abspath(CFG["paths"]["secrets"])


def weights() -> str:
    """Ruta al fichero JSON de pesos del modelo MLP de movimiento (IND-08)."""
    env = os.environ.get("CUSTODY_PATHS_WEIGHTS")
    if env:
        return abspath(env)
    return abspath(CFG["paths"]["weights"])


def anchor_weights() -> str:
    """Ruta al fichero JSON de pesos del discriminador Tier-2 de arrastre de ancla (IND-08)."""
    env = os.environ.get("CUSTODY_PATHS_ANCHOR_WEIGHTS")
    if env:
        return abspath(env)
    return abspath(CFG["paths"]["anchor_weights"])


def aoi():
    return tuple(CFG["aoi"]["bbox"])


def build_opt(key):
    return CFG["build"][key]


def ttl(kind):
    return CFG["cache"].get("ttl_" + kind) or None


if __name__ == "__main__":
    print("raiz    ", ROOT)
    print("config  ", CONFIG, "(existe)" if os.path.exists(CONFIG) else "(ausente, usando defaults)")
    print("aoi     ", aoi())
    for nm, fn in (("cache", cache), ("data", data)):
        p = fn()
        n = sum(len(f) for _, _, f in os.walk(p)) if os.path.isdir(p) else 0
        print("%-8s %-46s %d ficheros" % (nm, p, n))
    rs = records()
    if not rs:
        print("%-8s %-46s" % ("record", "(no encontrada)"))
    for i, r in enumerate(rs):
        n = sum(len(f) for _, _, f in os.walk(r))
        print("%-8s %-46s %d ficheros  %s" % ("record" if i == 0 else "extra",
                                             r, n, "RESPALDAR"))
    for st in stray_records():
        print("\nAVISO: hay grabacion fuera del almacen declarado")
        print("   %s  (%d ficheros diarios, ultima escritura hace %d min)"
              % (st["path"], st["day_files"],
                 (time.time() - st["newest_ms"] / 1000) / 60))
        print("   python3 ais_recorder/merge_store.py --from %s --apply" % st["path"])
        if st["active"]:
            print("   ALGO SIGUE ESCRIBIENDO AHI. Fusionar no basta: apunta la")
            print("   grabadora al almacen declarado o manana vuelve a pasar.")
