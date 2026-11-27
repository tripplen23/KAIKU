"""GNSS-Finland: calidad de la señal de navegación por satélite, en vivo.

QUE ES Y POR QUE ES LA MEJOR DE SU GRUPO.

Servicio abierto del Instituto Finlandés de Investigación Geoespacial,
encargado y financiado por Traficom. Mide la calidad de la señal de
navegación por satélite en las **47 estaciones de referencia de la red
FinnRef**: receptores geodésicos fijos, en tierra, a nivel del mar.

Comparado con GPSJAM --- que deriva la interferencia de lo que declaran las
aeronaves--- esto es otra liga para nuestro caso:

    GPSJAM          aeronaves, 10 km de altura, agregado 24 h, 1-2 dias tarde
    GNSS-Finland    estaciones fijas, nivel del mar, cada 30 s, AHORA

**33 de las 47 estaciones caen dentro de nuestra area de interes**, y ocho
bordean el Golfo de Finlandia --- Virolahti, Loviisa, Metsähovi, Raasepori---
que es exactamente donde Traficom situa el problema.

LO QUE MIDE, Y LO QUE NO.

Mide **relacion portadora-ruido** (`avgCnr`, en decibelios-hercio) por senal y
por constelacion, y la compara con un umbral propio del receptor para dar un
indicador de tres niveles: bueno, aceptable, pobre. O sea mide **degradacion
de la senal**, que es un sintoma.

NO dice la causa. Una caida del portadora-ruido la produce una interferencia
deliberada, pero tambien una antena mojada, una tormenta ionosferica o un arbol
que crecio. El servicio no distingue, y nosotros tampoco debemos.

Y NO MIDE EL MAR. Son estaciones en tierra. Que Virolahti vea degradacion no
prueba que un buque a 30 millas la viera; hace la hipotesis razonable, no
cierta. Es lo mismo que pasa con la cobertura de nuestros receptores AIS, y se
dice igual de claro.

VERIFICADO EL 2026-11-14, sin credenciales:

    GET https://gnss-finland.nls.fi:8080/api/capabilities
        -> 47 estaciones con nombre y coordenadas, los umbrales del receptor,
           y la escala del indicador: 0 bueno, 1 aceptable, 2 pobre
    GET https://gnss-finland.nls.fi:8080/api/sigstatus?stations=A,B,C
        -> por estacion y constelacion: satelites visibles, y por senal el
           numero de satelites, el portadora-ruido medio y el indicador

El servicio se publica en https://gnss-finland.nls.fi y el panel de datos vive
en el puerto 8080: no esta documentado en ningun sitio, se encontro mirando
que pide la propia pagina.

LICENCIA. La pagina del Instituto dice que el servicio «can be used by
anyone» y no publica terminos. Por eso entra en el registro de licencias como
**sin licencia declarada**: se puede mirar, y no se puede revender sin
preguntar primero. Hay que escribirles.
"""
import json
import logging
import math

from custody import net

LOG = logging.getLogger("custody.gnssfi")

BASE = "https://gnss-finland.nls.fi:8080"

# Treinta segundos es la cadencia a la que el propio servicio almacena
# observaciones (`obsStoreIntervalSec`). Pedirlo mas a menudo no trae nada
# nuevo; pedirlo mucho menos desperdicia la unica fuente en vivo del grupo.
STATUS_MAX_AGE_S = 30
# El catalogo de estaciones cambia cuando se instala una antena nueva, o sea
# casi nunca. Un dia es de sobra y evita una peticion en cada ciclo.
CAPS_MAX_AGE_S = 86400

QUALITY = {0: "good", 1: "satisfactory", 2: "poor"}


def capabilities(refresh=False):
    """Estaciones, umbrales del receptor y escala del indicador."""
    raw, _ = net.fetch(BASE + "/api/capabilities", ext="json", timeout=90,
                       max_age=CAPS_MAX_AGE_S, refresh=refresh)
    d = json.loads(raw.decode("utf-8"))
    if d.get("responseType") != "SUCCESS":
        raise RuntimeError("capabilities: %s" % d.get("responseType"))
    return d["responseObject"]


def stations(aoi=None, refresh=False):
    """[{tag, name, lat, lon, equipment}] dentro del area, si se da."""
    out = []
    for s in capabilities(refresh=refresh)["refStations"]:
        lon, lat = s["location"]["coordinates"]
        if aoi and not (aoi[0] <= lon <= aoi[2] and aoi[1] <= lat <= aoi[3]):
            continue
        out.append({"tag": s["tag"], "name": s["name"], "lat": lat, "lon": lon,
                    "equipment": s.get("equipmentTag"),
                    "positioning": (s.get("positioningType") or {}).get("descr")})
    return sorted(out, key=lambda x: x["tag"])


def status(tags, refresh=True):
    """Estado de senal por estacion. `refresh` por defecto: esto es el AHORA."""
    if not tags:
        return {}
    url = BASE + "/api/sigstatus?stations=" + ",".join(tags)
    raw, _ = net.fetch(url, ext="json", timeout=120, refresh=refresh,
                       max_age=STATUS_MAX_AGE_S)
    d = json.loads(raw.decode("utf-8"))
    out = {}
    for r in d.get("responseRecords") or []:
        out[r["refStationTag"]] = r.get("signalStatusByConstellation") or {}
    return out


def _worst(by_const):
    """El peor indicador de la estacion, y en que senal.

    SE TOMA EL PEOR, NO LA MEDIA. Una interferencia tipica afecta a una banda
    --- casi siempre la L1 de GPS, que es la que vale la pena atacar--- y
    promediarla con cuatro constelaciones sanas la borra. Lo que interesa es
    si ALGO esta degradado, y cual.
    """
    worst, where, sats = 0, None, 0
    for cid, c in (by_const or {}).items():
        sats += c.get("numVisibleSatellites") or 0
        for sid, s in (c.get("signalsQuality") or {}).items():
            ind = s.get("indicator")
            if ind is None:
                continue
            if ind > worst:
                worst, where = ind, {"signal": sid, "constellation": cid,
                                     "avg_cnr_db_hz": s.get("avgCnr"),
                                     "satellites": s.get("numSatellites")}
    return worst, where, sats


def snapshot(aoi=None, refresh=True):
    """FeatureCollection de estaciones con su estado actual, y stats."""
    caps = capabilities()
    thresholds = caps.get("equipment") or {}
    sts = stations(aoi=aoi)
    st_by_tag = status([s["tag"] for s in sts], refresh=refresh)
    feats, counts = [], {"good": 0, "satisfactory": 0, "poor": 0, "no_data": 0}
    newest = None
    for s in sts:
        by_const = st_by_tag.get(s["tag"])
        if not by_const:
            counts["no_data"] += 1
            q, where, sats = None, None, 0
        else:
            q, where, sats = _worst(by_const)
            counts[QUALITY[q]] += 1
        for c in (by_const or {}).values():
            lu = c.get("lastUpdate")
            if lu and (newest is None or lu > newest):
                newest = lu
        feats.append({"type": "Feature", "properties": {
            "tag": s["tag"], "name": s["name"],
            "quality": QUALITY.get(q) if q is not None else None,
            "quality_level": q,
            "worst_signal": where,
            "visible_satellites": sats,
            "equipment": s["equipment"],
            "measures": "carrier-to-noise ratio at a fixed ground station, "
                        "15 degree elevation mask, stored every 30 s",
            "caveat": "Signal degradation, not its cause: deliberate "
                      "interference looks the same as a wet antenna or an "
                      "ionospheric storm. And it is measured on land, not at "
                      "sea.",
        }, "geometry": {"type": "Point", "coordinates": [round(s["lon"], 6),
                                                         round(s["lat"], 6)]}})
    stats = {"stations": len(sts), "by_quality": counts,
             "newest_update": newest,
             "obs_interval_s": caps.get("obsStoreIntervalSec"),
             "elevation_mask_deg": round(math.degrees(
                 caps.get("minElevationForAvgCnr") or 0), 1),
             "history_s": caps.get("inMemHistoryLengthSec")}
    return {"type": "FeatureCollection", "features": feats,
            "properties": {
                "source": "GNSS-Finland, Finnish Geospatial Research Institute "
                          "(commissioned by Traficom)",
                "service": "https://gnss-finland.nls.fi",
                "quality_scale": QUALITY,
                "thresholds_db_hz": thresholds,
                **stats}}, stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from custody import paths
    fc, st = snapshot(aoi=paths.aoi())
    print(json.dumps(st, indent=1))
    for f in fc["features"]:
        p = f["properties"]
        w = p["worst_signal"] or {}
        print("  %-5s %-28s %-13s %2d sats  %s" % (
            p["tag"], p["name"][:28], p["quality"] or "-",
            p["visible_satellites"],
            ("peor: %s %.1f dB-Hz" % (w.get("signal"), w.get("avg_cnr_db_hz"))
             if w.get("avg_cnr_db_hz") else "")))
