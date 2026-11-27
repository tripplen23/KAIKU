"""FMI: viento y ola en un punto, para explicar una deriva.

POR QUE FMI Y NO COPERNICUS AQUI.

La regla del proyecto es ir a la fuente original y no al intermediario. FMI
NO es un proxy de Copernicus para esto: WAM y HARMONIE son modelos propios
del Instituto Meteorologico de Finlandia, corridos por ellos. Copernicus da
corriente y oleaje del Baltico; FMI da VIENTO, que Copernicus Marine no
publica porque no es una variable marina. Son complementarios, no duplicados.

PARA QUE SIRVE, EN CONCRETO.

IND-02 marca un buque que apunta a un sitio y se mueve a otro. Viento, ola y
corriente producen exactamente esa imagen. Sin ellos el indicador dice
«sospechoso»; con ellos puede decir «esto lo explica el viento» o, lo que
importa de verdad, «esto NO lo explica el viento».

Ese es el campo `drift_explained`, y es lo que convierte IND-02 de sospecha
en evidencia. Siguiendo a Zhang y Kujala (Aalto, 2023, mismo AOI), lo que
alimenta un modelo no son las variables sueltas sino los ANGULOS RELATIVOS
entre el rumbo del buque y cada forzamiento.

TRAMPAS MEDIDAS, que estan documentadas porque se tropezo con ellas:

  - Las boyas de oleaje devuelven NaN en noviembre: se retiran antes de la
    temporada de hielo. El modelo WAM funciona todo el ano. Por eso WAM es
    la fuente primaria y las boyas solo validacion estacional.
  - Un punto fuera de la rejilla util devuelve NaN sin error. Hay que
    comprobar que cae en mar abierto, no confiar en el HTTP 200.

Abierto, sin clave, sin registro, CC BY 4.0.
"""
import logging
import re
import urllib.parse

from custody import net

LOG = logging.getLogger("custody.fmi")

WFS = "https://opendata.fmi.fi/wfs"

QUERIES = {
    # Modelo de ola WAM. Todo el ano.
    "wave": ("fmi::forecast::wam::point::simple",
             "SigWaveHeight,WaveDirection,WavePeriod"),
    # Viento del modelo HARMONIE. Lo que Copernicus Marine no da.
    "wind": ("fmi::forecast::harmonie::surface::point::simple",
             "WindSpeedMS,WindDirection,WindGust"),
}


def _parse(xml):
    """Los `simple` devuelven ParameterValue/Time/Value. NaN = sin dato."""
    out = {}
    for blk in re.findall(r"<BsWfs:BsWfsElement.*?</BsWfs:BsWfsElement>", xml, re.S):
        name = re.search(r"<BsWfs:ParameterName>([^<]+)<", blk)
        val = re.search(r"<BsWfs:ParameterValue>([^<]+)<", blk)
        tm = re.search(r"<BsWfs:Time>([^<]+)<", blk)
        if not (name and val):
            continue
        try:
            v = float(val.group(1))
        except ValueError:
            continue
        if v != v:                      # NaN
            continue
        k = name.group(1)
        # El mas reciente de cada parametro.
        if k not in out or (tm and tm.group(1) > out[k][1]):
            out[k] = (v, tm.group(1) if tm else "")
    return {k: v for k, (v, _) in out.items()}


# Cuanto vale una respuesta de FMI antes de volver a pedirla. Los modelos
# publican paso horario, asi que 15 min es mas fino que el propio dato y
# acota el error a una fraccion de su cadencia. Sin esto la cache era
# ETERNA: el 2026-11-13 servia un pronostico de oleaje terminado cinco horas
# antes, y habria seguido envejeciendo indefinidamente.
MAX_AGE_S = 900


def point(lat, lon, what="wave", refresh=False, timeout=60):
    """Un punto, un modelo. Devuelve {} si cae fuera de la rejilla util."""
    q, params = QUERIES[what]
    url = WFS + "?" + urllib.parse.urlencode({
        "service": "WFS", "version": "2.0.0", "request": "getFeature",
        "storedquery_id": q, "latlon": "%.4f,%.4f" % (lat, lon),
        "parameters": params})
    raw, _ = net.fetch(url, refresh=refresh, ext="xml", timeout=timeout,
                       max_age=MAX_AGE_S)
    return _parse(raw.decode("utf-8", "replace"))


def forcing(lat, lon, refresh=False):
    """Viento y ola juntos, que es como se usan."""
    out = {}
    for what in ("wave", "wind"):
        try:
            out.update(point(lat, lon, what, refresh=refresh))
        except Exception as exc:
            LOG.warning("FMI %s en %.2f,%.2f: %s", what, lat, lon, exc)
    return out


def horizon(lat=59.8, lon=24.5, refresh=False):
    """Que ventana temporal cubre cada modelo AHORA MISMO, medida.

    No esta documentada en ningun sitio como un numero fijo: se pregunta. La
    respuesta de una `stored query` trae su propio eje de tiempos, asi que
    basta con leer el primero, el ultimo y el paso.

    Medido el 2026-11-13 a las 20:28Z:
        WAM (ola)        12 pasos horarios   21:00Z -> +11 h
        HARMONIE (viento) 50 pasos horarios  21:00Z -> +49 h

    EL DATO QUE SORPRENDE Y HAY QUE DECIR: las dos EMPIEZAN en la proxima
    hora en punto. La consulta de punto de FMI sirve PRONOSTICO, no historia.
    Para reconstruir un incidente pasado hace falta el reanalisis de CMEMS o
    las consultas de observacion de FMI, no esta.
    """
    out = {}
    for what in ("wave", "wind"):
        q, params = QUERIES[what]
        url = WFS + "?" + urllib.parse.urlencode({
            "service": "WFS", "version": "2.0.0", "request": "getFeature",
            "storedquery_id": q, "latlon": "%.4f,%.4f" % (lat, lon),
            "parameters": params})
        try:
            raw, _ = net.fetch(url, refresh=refresh, ext="xml", timeout=60,
                               max_age=MAX_AGE_S)
            xml = raw.decode("utf-8", "replace")
            ts = sorted(set(re.findall(r"<BsWfs:Time>([^<]+)<", xml)))
            if not ts:
                out[what] = {"ok": False, "reason": "sin eje temporal"}
                continue
            step = None
            if len(ts) > 1:
                step = int((_ms(ts[1]) - _ms(ts[0])) / 1000)
            out[what] = {"ok": True, "start": ts[0], "end": ts[-1],
                         "start_ms": _ms(ts[0]), "end_ms": _ms(ts[-1]),
                         "steps": len(ts), "step_s": step}
        except Exception as exc:
            out[what] = {"ok": False, "reason": str(exc)[:120]}
    return out


def _ms(iso):
    import datetime as _dt
    return int(_dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
               .timestamp() * 1000)


def rel_angle(a, b):
    """Diferencia angular minima, 0-180. El rasgo que usa Zhang."""
    if a is None or b is None:
        return None
    d = abs((a - b + 180.0) % 360.0 - 180.0)
    return round(d, 1)


def explain_drift(heading_deg, cog_deg, f):
    """¿Explica el forzamiento el angulo de deriva observado?

    Devuelve un dict listo para colgar de la evidencia de IND-02. NO afirma
    causa: dice si el angulo observado es COMPATIBLE con el forzamiento, que
    es lo unico que el dato soporta.

    La regla: el buque es empujado a sotavento, asi que si el cangrejeo va
    hacia donde sopla y la magnitud da, el viento lo explica. Si el cangrejeo
    va contra el forzamiento, queda algo por explicar -- y eso es lo
    interesante.
    """
    if heading_deg is None or cog_deg is None:
        return None
    crab = (cog_deg - heading_deg + 180.0) % 360.0 - 180.0   # + = a estribor
    wind_from = f.get("WindDirection")
    wave_from = f.get("WaveDirection")
    out = {
        "crab_deg": round(crab, 1),
        "wind_speed_ms": f.get("WindSpeedMS"),
        "wind_rel_deg": rel_angle(heading_deg, wind_from),
        "wave_height_m": f.get("SigWaveHeight"),
        "wave_rel_deg": rel_angle(heading_deg, wave_from),
    }
    if wind_from is None:
        out["drift_explained"] = None
        out["why"] = "No wind model value at this point — FMI's grid does not cover it."
        return out
    # Direccion a la que empuja = de donde viene + 180.
    push = (wind_from + 180.0) % 360.0
    side = (push - heading_deg + 180.0) % 360.0 - 180.0      # + = empuja a estribor
    same = (side >= 0) == (crab >= 0)
    strong = (f.get("WindSpeedMS") or 0) >= 8.0 or (f.get("SigWaveHeight") or 0) >= 1.5
    out["push_side_deg"] = round(side, 1)
    out["same_side"] = same
    if same and strong:
        out["drift_explained"] = True
        out["why"] = ("The vessel is crabbing to the side the forcing pushes, "
                      "and the forcing is strong enough: wind %.1f m/s, wave %.1f m. "
                      "This looks like drift, not steering."
                      % (f.get("WindSpeedMS") or 0, f.get("SigWaveHeight") or 0))
    elif same:
        out["drift_explained"] = None
        out["why"] = ("Crabbing to the side the forcing pushes, but the forcing is "
                      "weak (wind %.1f m/s, wave %.1f m). Compatible, not sufficient."
                      % (f.get("WindSpeedMS") or 0, f.get("SigWaveHeight") or 0))
    else:
        out["drift_explained"] = False
        out["why"] = ("The vessel is crabbing AGAINST the side wind and wave push it. "
                      "The forcing does not explain this angle, which leaves something "
                      "to explain.")
    return out


if __name__ == "__main__":
    import json
    import sys
    logging.basicConfig(level=logging.INFO)
    lat = float(sys.argv[1]) if len(sys.argv) > 2 else 59.80
    lon = float(sys.argv[2]) if len(sys.argv) > 2 else 24.50
    f = forcing(lat, lon)
    print("forzamiento en %.2f N %.2f E:" % (lat, lon))
    for k in sorted(f):
        print("   %-18s %s" % (k, f[k]))
    print()
    for hd, cg in ((10, 20), (10, 0)):
        d = explain_drift(hd, cg, f)
        print("rumbo %d, COG %d -> drift_explained=%s" % (hd, cg, d["drift_explained"]))
        print("   ", d["why"])
