"""Que no entre en el producto nada que no se pueda vender.

Esta prueba existe por un fallo real: el 13-11-2026 las isobatas de HELCOM
estuvieron dentro una tarde, y sus condiciones dicen «Any commercial use is
prohibited». No se noto porque no habia donde mirarlo.

Lo que comprueba:
  1. Toda fuente que cita el manifest del build esta en el registro.
  2. Ninguna fuente PROHIBIDA explicitamente se esta usando. El silencio del
     publicador es otra cosa: `ask_before_selling` deja mirar y citar, y sale
     listado al final para que no se olvide antes de vender.
  3. Toda fuente usada declara atribucion, porque todas las licencias
     abiertas que tocamos la exigen y es lo primero que se olvida.
"""
import json
import os
import sys

try:
    import tomllib
except ImportError:
    tomllib = None


def _load_toml(path):
    if tomllib is not None:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    out = {}
    sec = None
    lines = open(path, "r", encoding="utf-8").read().splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i].strip()
        i += 1
        if not raw or raw.startswith("#"):
            continue
        if raw.startswith("[") and raw.endswith("]"):
            sec = out.setdefault(raw[1:-1].strip(), {})
            continue
        if "=" in raw and sec is not None:
            k, v = raw.split("=", 1)
            k, v = k.strip(), v.strip()
            if v.startswith('"""'):
                body = [v[3:]]
                while not body[-1].endswith('"""') and i < len(lines):
                    body.append(lines[i])
                    i += 1
                sec[k] = "\n".join(body)[:-3]
            elif v in ("true", "false"):
                sec[k] = (v == "true")
            elif v.startswith("["):
                body = [v]
                while not body[-1].rstrip().endswith("]") and i < len(lines):
                    body.append(lines[i].strip())
                    i += 1
                sec[k] = json.loads(" ".join(body))
            elif v.startswith('"') and v.endswith('"'):
                sec[k] = v[1:-1]
            else:
                sec[k] = v
    return out

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

REG = os.path.join(ROOT, "config", "licences.toml")

# Lo que cada capa del build consume. Si se anade una capa con una fuente
# nueva, se anade aqui y en el registro; si no, esta prueba lo caza.
LAYER_SOURCE = {
    "tracks": "fintraffic_ais", "positions": "fintraffic_ais",
    "alerts": "fintraffic_ais", "suppressed": "fintraffic_ais",
    "ais_coverage": "fintraffic_ais",
    "coastline": "helcom_coastline", "basins": "helcom_subbasins",
    "bathymetry": "emodnet_dtm", "depth_grid": "emodnet_dtm",
    "depth_map": "emodnet_dtm",
    "corridors": "osm", "corridors_other": "osm", "ports": "osm",
    "restrictions": "vayla", "anchor_ban": "vayla",
    "wrecks": "helcom_human_activities", "munitions": "helcom_human_activities",
    "military_areas": "helcom_human_activities",
    "msp_restricted": "helcom_human_activities",
    "sentinel1": "copernicus", "scenes": "copernicus",
    "vessel_info": "wikimedia_commons",
    "marine": "copernicus_marine", "aishub": "aishub",
    "emodnet": "emodnet_human_activities",
    "gnss_stations": "gnss_finland", "gps_interference": "gpsjam",
    "gfw_events": "gfw", "gfw_grid": "gfw",
}


def main():
    reg = _load_toml(REG)
    bad = []

    from custody import paths
    man_path = paths.data("manifest.json")
    if not os.path.exists(man_path):
        print("    FALLO no hay manifest en %s -- sin el, esta prueba no "
              "comprueba nada y pasar seria mentira" % man_path)
        return 1
    with open(man_path) as fh:
        layers = (json.load(fh).get("layers") or {})
    if not layers:
        print("    FALLO el manifest no declara capas")
        return 1

    usadas = set()
    for layer, st in layers.items():
        if st.get("status") not in ("ok",):
            continue
        src = LAYER_SOURCE.get(layer)
        if src is None:
            bad.append("la capa '%s' esta en el build y no declara fuente "
                       "(anadela a LAYER_SOURCE)" % layer)
            continue
        if src not in reg:
            bad.append("la capa '%s' cita '%s', que no esta en el registro"
                       % (layer, src))
            continue
        usadas.add(src)

    # TRES ESTADOS, NO DOS. «Prohibido» y «no se sabe» no son lo mismo y la
    # accion que piden tampoco:
    #
    #   commercial = true      se puede vender. Adelante.
    #   commercial = false     PROHIBIDO explicitamente por quien lo publica.
    #                          Fuera del producto, sin discusion. Es el caso de
    #                          las isobatas de HELCOM: «any commercial use is
    #                          prohibited».
    #   ask_before_selling     el publicador NO DICE NADA. Se puede mirar y
    #                          citar; venderlo exige preguntar primero. Es el
    #                          caso de GPSJAM y GNSS-Finland, que no publican
    #                          terminos en ninguna parte.
    #
    # Tratar el silencio como prohibicion dejaria fuera dato publico util; y
    # tratarlo como permiso es como se firma un contrato que no se puede
    # cumplir. Por eso el tercer estado existe y por eso se LISTA al final:
    # que no bloquee el build no significa que se pueda olvidar.
    pendientes = []
    for src in sorted(usadas):
        e = reg[src]
        if not e.get("commercial"):
            if e.get("ask_before_selling"):
                pendientes.append(src)
            else:
                bad.append("FUENTE NO COMERCIAL EN EL PRODUCTO: %s (%s)"
                           % (src, e.get("name")))
        if not e.get("attribution"):
            bad.append("'%s' se usa y no declara atribucion" % src)
        if e.get("ask_before_selling") and e.get("commercial"):
            bad.append("'%s' no puede ser a la vez comercial y pendiente de "
                       "preguntar: decide" % src)

    print("  %d capas en el build, %d fuentes distintas" % (len(layers), len(usadas)))
    print("  registro: %d fuentes, %d marcadas como no comerciales"
          % (len(reg), sum(1 for v in reg.values() if not v.get("commercial"))))
    for src in sorted(usadas):
        print("    ok  %-26s %s" % (src, reg[src].get("licence")))
    for src in pendientes:
        print("    PREGUNTAR ANTES DE VENDER  %-14s %s"
              % (src, reg[src].get("ask_contact") or reg[src].get("url")))
    for b in bad:
        print("    FALLO %s" % b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
