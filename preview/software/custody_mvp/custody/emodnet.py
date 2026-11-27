"""EMODnet Human Activities: la linea base de trafico de todo el AOI.

QUE PROBLEMA RESUELVE, EXACTAMENTE.

Nuestra cobertura AIS es el 21 % del AOI y muere hacia los 57 N. Sobre el 79 %
restante la herramienta no puede decir nada --- ni siquiera si lo que ve es
raro, porque no sabe que es normal ahi. Un indicador que marca «este buque se
desvia» necesita una referencia de por donde se pasa, y esa referencia no
puede salir de nuestra propia grabacion: es justo lo que nos falta.

EMODnet publica esa referencia para TODO el mar, construida con AIS que
nosotros no tenemos. No sustituye a nuestra grabacion --- no sirve para ver
que pasa ahora, es mensual y agregada--- sino que le da el fondo contra el
que medir.

DOS PRODUCTOS, Y LA DIFERENCIA IMPORTA MUCHO.

  Route Density (EMSA)      2019-01 -> el mes pasado.  1 km.
      Construida por la Agencia Europea de Seguridad Maritima con el AIS de
      la propia UE. Es la que esta AL DIA: en noviembre de 2026 ya tiene
      octubre. Esta es la linea base operativa.

  Vessel Density (Cogea)    2017-01 -> 2024-12.  1 km.  h/km2 al mes.
      Construida para EMODnet con AIS COMPRADO a CLS, ORBCOMM y
      vesseltracker.com. Se actualiza una vez al ano, asi que va unos once
      meses por detras. A cambio trae trece tipos de buque por separado,
      incluido «Military and Law Enforcement», que la de EMSA no desglosa.
      Es la climatologia, no el presente.

      AVISO QUE PUBLICA EL PROPIO SERVICIO Y HAY QUE REPETIR: en 2024 su
      proveedor perdio dato de satelite desde junio, asi que el segundo
      semestre de 2024 esta menos poblado que los anos anteriores. Para
      comparar con un noviembre, usa 2023.

Las dos en 1x1 km, las dos cubriendo el AOI entero, las dos CC BY 4.0 con
atribucion a EMODnet Human Activities y a CLS.

INFRAESTRUCTURA: UNA SEGUNDA OPINION SOBRE LOS CABLES.

Nuestros corredores salen de OpenStreetMap: 6.754 elementos, 133 con nombre.
Es cartografia comunitaria, y para un producto cuyo objeto ES el cable eso es
un punto debil. EMODnet publica la agregacion oficial que Cogea mantiene para
la Comision --- telecomunicaciones y energia por separado--- actualizada cada
ano. Aqui entra como capa aparte y declarada, no sustituyendo a OSM: cual es
la buena se decide mirandolas juntas, no en silencio.

CADENCIA: SE LEE, NO SE ESCRIBE. El WMS declara la dimension `time` de cada
capa como lista de instantes. De ahi salen el primero, el ultimo y el paso,
y de ahi sale el carril de la linea de tiempo. Una cadencia escrita a mano se
queda vieja sin avisar.
"""
import logging
import re
import urllib.parse

from custody import net

LOG = logging.getLogger("custody.emodnet")

WMS = "https://ows.emodnet-humanactivities.eu/wms"

# Un dia. Cada mes aparece un instante nuevo en la dimension `time`, asi que
# una cache eterna congelaria la linea base en el mes en que se compilo --- el
# mismo fallo que tenia el pronostico de FMI.
CAPS_TTL_S = 86400

#  id de capa WMS          grupo        nombre                        para que
CURATED = [
    ("routedensity_all", "baseline", "Route density, all types",
     "The current baseline. EMSA builds it from the EU's own AIS and it is "
     "only a month behind, so it answers 'is this route normally used' over "
     "the whole AOI, including the 79 % we cannot hear."),
    ("routedensity_01", "baseline", "Route density, cargo",
     "Cargo is the bulk of Baltic traffic; a cable corridor crossed by cargo "
     "is being crossed by the normal flow."),
    ("routedensity_04", "baseline", "Route density, tankers",
     "The shadow fleet is tankers. Where tankers normally go is the reference "
     "for where one of them has no business being."),
    ("routedensity_02", "baseline", "Route density, fishing",
     "Fishing explains loitering and slow speed over ground that would "
     "otherwise look like a vessel working a cable."),

    ("vesseldensity_allavg", "climatology", "Vessel density, yearly average",
     "The long baseline: 2017-2024 in hours per square kilometre. Use it for "
     "'has traffic here changed', not for what is happening now."),
    ("vesseldensity_10", "climatology", "Vessel density, tankers (monthly)",
     "Monthly tanker climatology. Compare the same month across years; the "
     "shadow fleet shows up as a change, not as an absolute number."),
    ("vesseldensity_11", "climatology", "Vessel density, military and law enforcement",
     "The only open layer that separates military and law-enforcement traffic. "
     "It tells you which patrol patterns are routine before you read one as a "
     "response to something."),
    ("vesseldensity_01", "climatology", "Vessel density, fishing (monthly)",
     "Fishing is seasonal, so the monthly series is the one that matters for "
     "deciding whether this November looks like other Novembers."),

    ("telecablesactual", "infrastructure", "Telecom cables (EMODnet)",
     "The official EU aggregation, maintained by Cogea for the Commission. "
     "Ours come from OpenStreetMap, which is community-mapped: this is the "
     "second opinion on the thing the product exists to protect."),
    ("powercables", "infrastructure", "Power cables (EMODnet)",
     "Estlink and the interconnectors. A power cable cut is the incident that "
     "put this project on the map, and they are a separate dataset from telecom."),
    ("pipelines", "infrastructure", "Pipelines (EMODnet)",
     "Balticconnector was a pipeline, not a cable. Same threat, same seabed, "
     "different dataset."),
    ("windfarmspoly", "infrastructure", "Wind farms (EMODnet)",
     "Export cables run from every farm to shore, and service traffic around "
     "one explains vessels sitting still over infrastructure."),
]

ATTRIBUTION = ("EMODnet Human Activities; vessel density © Cogea from AIS by "
               "CLS, ORBCOMM and vesseltracker.com; route density © EMSA")

# El aviso que publica el propio servicio. Va en la capa, no en una nota.
CAVEAT_2024 = ("Vessel density 2024 is thin: the AIS provider lost satellite "
               "data from June 2024 onwards. Compare against 2023, not 2024.")


def _capabilities(refresh=False):
    url = ("%s?service=WMS&version=1.3.0&request=GetCapabilities" % WMS)
    raw, cached = net.fetch(url, refresh=refresh, ext="xml", timeout=300,
                            max_age=CAPS_TTL_S)
    return raw.decode("utf-8", "replace"), cached


def _layer_block(xml, name):
    i = xml.find("<Name>%s</Name>" % name)
    if i < 0:
        return None
    a = xml.rfind("<Layer", 0, i)
    b = xml.find("</Layer>", i)
    return xml[a:b] if a >= 0 and b > i else None


def _time_dim(blk):
    """La dimension `time`: una LISTA de instantes, no un intervalo.

    Copernicus declara `inicio/fin/paso`; EMODnet enumera cada mes. Son dos
    gramaticas distintas de la misma idea y hay que leer las dos, porque de
    aqui sale el carril de la linea de tiempo.
    """
    m = re.search(r'<Dimension[^>]*name="time"[^>]*>([^<]*)</Dimension>', blk, re.S)
    if not m:
        return None
    vals = [v.strip() for v in m.group(1).split(",") if v.strip()]
    if not vals:
        return None
    dflt = re.search(r'default="([^"]*)"', m.group(0))
    step = None
    if len(vals) > 1:
        step = int((_ms(vals[1]) - _ms(vals[0])) / 1000)
    return {"start": vals[0], "end": vals[-1], "instants": len(vals),
            "step_s": step, "default": dflt.group(1) if dflt else vals[-1],
            "values": vals}


def _ms(iso):
    import datetime as _dt
    try:
        return int(_dt.datetime.fromisoformat(
            iso.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return None


def _legend(name):
    return (WMS + "?" + urllib.parse.urlencode({
        "service": "WMS", "version": "1.3.0", "request": "GetLegendGraphic",
        "layer": name, "format": "image/png"}))


def catalogue(refresh=False):
    """(dict para el visor, stats). Mismo contrato que marine.catalogue()."""
    xml, cached = _capabilities(refresh=refresh)
    layers, missing = [], []
    for name, group, title, why in CURATED:
        blk = _layer_block(xml, name)
        if blk is None:
            missing.append(name)
            continue
        wms_title = re.search(r"<Title>([^<]*)</Title>", blk)
        td = _time_dim(blk)
        layers.append({
            "id": "emod_" + name,
            "wms_layer": name, "group": group, "name": title, "why": why,
            "service_title": wms_title.group(1) if wms_title else "",
            "wms": WMS,
            "legend": _legend(name),
            "step_s": td["step_s"] if td else None,
            "time": ({"start_ms": _ms(td["start"]), "end_ms": _ms(td["end"]),
                      "start": td["start"], "end": td["end"],
                      "instants": td["instants"], "step_s": td["step_s"],
                      "default": td["default"],
                      # Los instantes exactos: el visor tiene que pedir UNO de
                      # ellos, no el mes redondeado, porque fuera de la lista
                      # el servicio devuelve una tesela vacia que sobre el
                      # mapa se lee como «aqui no pasa nadie».
                      "values": td["values"]}
                     if td else None),
        })
    st = {"layers": len(layers), "missing": missing, "from_cache": cached,
          "with_time": sum(1 for l in layers if l["time"])}
    if missing:
        LOG.warning("capas ausentes del WMS: %s", ", ".join(missing))
    return {"attribution": ATTRIBUTION, "wms": WMS, "caveat": CAVEAT_2024,
            "layers": layers}, st


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    cat, st = catalogue()
    print(json.dumps(st, indent=1))
    for l in cat["layers"]:
        t = l["time"] or {}
        print("  %-12s %-40s %-9s %s -> %s  (%s instantes)"
              % (l["group"], l["name"][:40],
                 ("%d s" % l["step_s"]) if l["step_s"] else "sin tiempo",
                 (t.get("start") or "")[:10], (t.get("end") or "")[:10],
                 t.get("instants", "-")))
