"""Copernicus Marine (CMEMS) para el Baltico: catalogo de capas WMTS.

QUE RESUELVE.

IND-02 dispara cuando un buque apunta a un sitio y se mueve a otro. Viento,
ola y corriente producen exactamente esa imagen, asi que sin ellos el
indicador no puede distinguir DERIVA de MANIOBRA. Esto trae el forzamiento.

FUENTE ORIGINAL, NO INTERMEDIARIO. FMI sirve ola y viento y es una fuente
propia para sus modelos (WAM, HARMONIE), pero la corriente no la da nadie
mas que CMEMS, y el reanalisis para reconstruir incidentes pasados tampoco.

VERIFICADO EL 2026-11-13: el WMTS de Copernicus Marine responde SIN
credenciales. GetCapabilities y GetTile devuelven 200 y un PNG de 256x256.
Esto importa porque el acceso programatico al dato (OPeNDAP, la toolbox)
SI exige cuenta: las capas se pueden pintar hoy, los numeros crudos no.

LOS TRES PRODUCTOS, que son los que pidio el usuario:

    BALTICSEA_ANALYSISFORECAST_PHY_003_006   corrientes, hielo, T, S, nivel
    BALTICSEA_ANALYSISFORECAST_WAV_003_010   oleaje, deriva de Stokes
    BALTICSEA_MULTIYEAR_PHY_003_011          reanalisis, para incidentes pasados

EL LIMITE QUE HAY QUE DECIR EN VOZ ALTA. Medido en la iteracion anterior:
87 grados de error RMS en la direccion de la corriente superficial, validado
contra siete fondeos para todo el mar. Sirve para afirmar «habia corriente»,
no para calcular una deriva concreta. Va escrito en la capa, no en una nota
al pie, porque es la clase de cosa que un jurado pregunta.

LA ETIQUETA DEL DATASET CAMBIA. El identificador lleva un sufijo de version
--`_202411`, `_202611`-- que Copernicus rota en cada Service Release. Se
elige la MAS ALTA al compilar en vez de fijarla: una URL con la etiqueta vieja
deja de servir teselas sin avisar.
"""
import html
import json
import logging
import re

from custody import net

LOG = logging.getLogger("custody.marine")

WMTS = "https://wmts.marine.copernicus.eu/teroWmts"

PRODUCTS = {
    "phy": "BALTICSEA_ANALYSISFORECAST_PHY_003_006",
    "wav": "BALTICSEA_ANALYSISFORECAST_WAV_003_010",
    "rean": "BALTICSEA_MULTIYEAR_PHY_003_011",
    # El producto GLOBAL de Mercator Ocean. Ver GLOBAL_WHY abajo: entra como
    # contraste declarado, no como mejora.
    "glob": "GLOBAL_ANALYSISFORECAST_PHY_001_024",
}

# QUIEN HACE QUE, porque se pregunta y la respuesta no es la que parece.
#
#   Mercator Ocean International  implementa y opera el Servicio Copernicus
#                                 Marine entero, y produce los productos
#                                 GLOBALES.
#   SMHI (Norrkoping)             produce el producto del BALTICO que usa esta
#                                 herramienta, dentro del Baltic MFC, con DMI
#                                 (Copenhague) como service desk local.
#
# O sea: la corriente que ya pinta esta aplicacion viene del servicio que
# opera Mercator, pero el modelo es de SMHI. NEMO v4.0, 1 MILLA NAUTICA de
# resolucion, hasta 56 niveles, asimilando SST de satelite, concentracion de
# hielo y perfiles T/S in situ, forzado con deriva de Stokes del producto de
# oleaje baltico. Se actualiza DOS VECES AL DIA con seis dias de pronostico.
PRODUCERS = {
    "phy": "SMHI, Baltic MFC (Copernicus Marine, operated by Mercator Ocean International)",
    "wav": "Baltic MFC (Copernicus Marine, operated by Mercator Ocean International)",
    "rean": "Baltic MFC reanalysis (Copernicus Marine)",
    "glob": "Mercator Ocean International, global ocean analysis and forecast",
}

# POR QUE EL GLOBAL ENTRA COMO CONTRASTE Y NO COMO FUENTE PRINCIPAL.
#
# Resolucion: 1/12 grados, unos 8 km, contra 1 milla nautica (1,85 km) del
# modelo baltico. El Golfo de Finlandia tiene entre 50 y 100 km de ancho: con
# celdas de 8 km son seis o doce a lo ancho, y la costa entra en la celda. Para
# este mar el modelo baltico es mejor, y cambiar a global seria perder detalle.
#
# Lo que el global SI aporta y el baltico no publica: la VELOCIDAD TOTAL
# -- euleriana + olas + marea juntas-- que es lo que de verdad transporta un
# casco. El baltico publica la corriente euleriana (aunque este forzado con
# Stokes). Ese es el unico motivo de tenerlo aqui.
#
# Y el limite honesto: el Baltico es MICROMAREAL, unos centimetros de carrera.
# La componente de marea que el global anade pesa poco en este mar. Sirve de
# comprobacion cruzada --- «¿los dos modelos dicen lo mismo?»-- no de mejora.
GLOBAL_RES_KM = 8
BALTIC_RES_KM = 1.85

# Lo que se publica, y por que. No las 68 variables: las que responden a una
# pregunta que esta herramienta hace.
#   group  agrupa en el panel
#   why    que pregunta responde. Si no hay respuesta, la capa sobra.
CURATED = [
    ("phy", "sea_water_velocity", "currents", "Surface current",
     "The one thing FMI cannot give. A vessel crabbing with the current is "
     "drifting; crabbing against it is steering."),
    ("phy", "sea_ice_velocity", "ice", "Sea ice drift",
     "Ice moves, and it moves ships with it. A track that follows the ice is "
     "not navigating."),
    ("phy", "siconc", "ice", "Sea ice concentration",
     "Where ice is, traffic concentrates into channels and a cable is easier "
     "to reach by accident."),
    ("phy", "sithick", "ice", "Sea ice thickness", "How much ice, not just whether."),
    ("phy", "thetao", "water", "Sea surface temperature", "Context, and the "
     "variable most often needed to make sense of ice."),
    ("phy", "so", "water", "Salinity",
     "The Baltic is brackish and stratified; salinity marks the water masses."),
    ("phy", "sla", "water", "Sea level",
     "Surge changes what depth a hull actually has under it."),
    ("phy", "mlotst", "water", "Mixed layer depth", "Stratification context."),

    ("wav", "VHM0", "waves", "Significant wave height",
     "Sea state. Above a few metres, a crabbing angle explains itself."),
    ("wav", "VMDR", "waves", "Mean wave direction",
     "The angle that matters: wave direction against vessel heading."),
    ("wav", "VTM10", "waves", "Mean wave period", "Long period means swell, not local wind."),
    ("wav", "VTPK", "waves", "Peak wave period", "Which part of the spectrum dominates."),
    ("wav", "VHM0_SW1", "waves", "Primary swell height",
     "Swell arrives from elsewhere; wind sea is local. Separating them "
     "separates two different explanations for the same drift."),
    ("wav", "VHM0_WW", "waves", "Wind wave height", "The locally generated part."),
    ("wav", "VSDX", "waves", "Stokes drift, east",
     "Wave-induced transport. Small, persistent, and exactly the kind of "
     "forcing a short AIS window cannot distinguish from intent."),
    ("wav", "VSDY", "waves", "Stokes drift, north", "The northward component."),

    ("rean", "sea_water_velocity", "reanalysis", "Current (reanalysis)",
     "For reconstructing an incident: what the water was doing on the day, "
     "not what it is doing now."),
    ("rean", "siconc", "reanalysis", "Sea ice (reanalysis)", "Ice on the day."),
    ("rean", "thetao", "reanalysis", "Temperature (reanalysis)", "Conditions on the day."),
    ("rean", "sla", "reanalysis", "Sea level (reanalysis)", "Surge on the day."),
]

# Capas atadas a un conjunto de datos CONCRETO, porque lo que las hace utiles
# es ese conjunto y no la variable. El selector normal se queda con la
# etiqueta de version mas alta, y aqui eso elegiria el dataset equivocado: la
# velocidad total vive en `merged-uv` (etiqueta 202211), mas vieja que el
# `0.083deg` (202406) que solo trae la corriente euleriana.
#
# Fijar una etiqueta es justo lo que el selector evita, asi que esto se
# COMPRUEBA: si el dataset desaparece de las capacidades, el build avisa en vez
# de servir teselas vacias en silencio.
PINNED = [
    ("glob", "sea_water_velocity", "merged-uv", "currents_global",
     "Total surface current (global)",
     "Eulerian flow, waves and tide added together, which is what actually "
     "transports a hull. The Baltic model publishes the Eulerian current "
     "only. Mercator Ocean's own global model, 1/12 deg (~8 km) against the "
     "Baltic model's 1 nm (~1.85 km): a cross-check at coarser resolution, "
     "not an upgrade. The Baltic is microtidal, so the tidal part it adds is "
     "small here."),
    ("glob", "utide", "merged-uv", "currents_global",
     "Tidal current, eastward (global)",
     "The tidal component on its own. Worth one look to see how little of the "
     "Baltic current is tide: if it is small, wind and pressure explain the "
     "rest, and that is the useful conclusion."),
]

CURRENT_DIR_RMS_DEG = 87   # el error medido. Va a la capa, no a una nota.

# Duraciones ISO 8601 que publica este servicio, en segundos. No se pretende
# un parser general: son estas cinco, y P1M/P1Y son nominales porque solo se
# usan para ordenar y para escribir «mensual» en una etiqueta.
_ISO_STEP = {"PT900S": 900, "PT15M": 900, "PT1H": 3600, "PT3H": 10800,
             "P1D": 86400, "P1M": 2592000, "P1Y": 31536000}


def _parse_time_dim(blk):
    """start/end/step de la dimension `time` que declara la capa.

    POR QUE IMPORTA MAS DE LO QUE PARECE. De esto sale la CADENCIA, y la
    cadencia es lo que decide si dos capas se pueden superponer en el mismo
    instante. Tambien destapo un fallo real: Copernicus publica la misma
    variable como media diaria, media mensual, horaria y de 15 minutos, y el
    selector se quedaba con la que apareciese primero en el XML. Resultado:
    la corriente que se pintaba junto a una derrota era una MEDIA DE 24 H y
    el nivel del mar una MEDIA DE 30 DIAS, en una herramienta cuyo valor es
    decir que pasa ahora.
    """
    m = re.search(r"<Dimension>\s*<ows:Identifier>time</ows:Identifier>(.*?)</Dimension>",
                  blk, re.S)
    if not m:
        return None
    body = m.group(1)
    vals = re.findall(r"<Value>([^<]+)</Value>", body)
    if not vals:
        return None
    starts, ends, steps = [], [], []
    for v in vals:
        parts = v.strip().split("/")
        starts.append(parts[0])
        ends.append(parts[1] if len(parts) > 1 else parts[0])
        if len(parts) > 2:
            steps.append(_ISO_STEP.get(parts[2]))
    dflt = re.search(r"<Default>([^<]*)</Default>", body)
    step = min([x for x in steps if x], default=None)
    return {"start": min(starts), "end": max(ends), "step_s": step,
            "default": dflt.group(1) if dflt else None,
            "instants": None if step else len(vals)}


def _iso_ms(s):
    """ISO 8601 -> epoch ms. Sin dependencias: estas cadenas son todas Z."""
    import datetime as _dt
    try:
        t = s.replace("Z", "+00:00")
        return int(_dt.datetime.fromisoformat(t).timestamp() * 1000)
    except Exception:
        return None


def _capabilities(product, refresh=False):
    url = ("%s/%s?service=WMTS&version=1.0.0&request=GetCapabilities"
           % (WMTS, product))
    raw, cached = net.fetch(url, refresh=refresh, ext="xml", timeout=300)
    return raw.decode("utf-8", "replace"), cached


def _newest(xml):
    """variable -> dict con etiqueta, identificador, titulo, estilo y leyenda.

    Se queda con la etiqueta mas alta por variable. Copernicus publica varias
    versiones del mismo dataset a la vez y la vieja deja de servir teselas sin
    previo aviso.

    EL ESTILO Y LA LEYENDA SE LEEN, NO SE CONSTRUYEN. El servicio declara
    `<Style>` con su `LegendURL` para cada capa: 166 en el producto de oleaje.
    Fabricar esa URL a mano fue el primer intento y daba 400, porque hay que
    acertar el estilo (`cmap:amp`, `cmap:viridis`...) y el unico formato que
    acepta. Preguntarselo al servicio es mas corto y no se rompe cuando
    cambien la paleta.

    Hay una trampa en el propio XML: el FORMAT viene DOBLEMENTE codificado
    (`image%252Fsvg%252Bxml`, donde %25 es un `%`). Tal cual, 400. Se
    normaliza aqui.
    """
    best = {}
    for m in re.finditer(r"<Layer[^>]*>(.*?)</Layer>", xml, re.S):
        blk = m.group(1)
        im = re.search(r"<ows:Identifier>([^<]+)</ows:Identifier>", blk)
        tm = re.search(r"<ows:Title>([^<]*)</ows:Title>", blk)
        if not im or im.group(1).count("/") != 2:
            continue
        ident = im.group(1)
        _, ds, var = ident.split("/")
        tag = ds.rsplit("_", 1)[-1]
        if "--ext--" in tag:          # mallas y batimetria auxiliar
            continue
        tdim = _parse_time_dim(blk)
        step = (tdim or {}).get("step_s") or 10 ** 9

        # ORDEN DE PREFERENCIA: primero la etiqueta de version mas alta
        # --una etiqueta vieja deja de servir teselas sin avisar-- y DENTRO
        # de esa etiqueta, la cadencia mas fina.
        #
        # El criterio anterior era solo la etiqueta, asi que entre la media
        # diaria y la serie de 15 minutos de la MISMA version ganaba la que
        # apareciera primero en el XML. Por ese azar la corriente se pintaba
        # como media de 24 h y el nivel del mar como media de 30 dias.
        if var in best:
            prev = best[var]
            if (tag, -step) <= (prev["dataset_tag"], -prev["step_s"]):
                continue

        # Elegir ESTILO. La primera version saltaba cualquier estilo con coma,
        # y asi se quedaban sin leyenda justo las tres capas vectoriales --
        # corriente y deriva del hielo -- cuyos estilos se llaman
        # `cmap:speed,vectorStyle:solid`. Eran las mas importantes.
        #
        # Preferencias, en orden:
        #   solidAndVector  color por magnitud Y flechas de direccion. Para
        #                   una corriente, la direccion ES el dato.
        #   solid           solo color
        #   el primero que haya
        # Las variantes `logScale` se descartan: una escala logaritmica de
        # corriente no se lee de un vistazo.
        cands = []
        for sm in re.finditer(r"<Style([^>]*)>(.*?)</Style>", blk, re.S):
            sid = re.search(r"<ows:Identifier>([^<]+)</ows:Identifier>", sm.group(2))
            if not sid or "logScale" in sid.group(1):
                continue
            lm = re.search(r'<LegendURL[^>]*xlink:href="([^"]+)"', sm.group(2))
            cands.append((sid.group(1),
                          _fix_legend(html.unescape(lm.group(1))) if lm else None))
        style, legend = "", None
        if cands:
            pick = (next((c for c in cands if "solidAndVector" in c[0]), None)
                    or next((c for c in cands if "vectorStyle:solid" in c[0]), None)
                    or cands[0])
            style, legend = pick

        title = tm.group(1) if tm else ""
        best[var] = {
            "dataset_tag": tag, "layer": ident, "dataset": ds,
            "title": title.split(" - ", 1)[-1] if " - " in title else title,
            "style": style or "", "legend": legend,
            "step_s": step, "time": tdim,
        }
    return best


def _fix_legend(url):
    """Deshace el doble escapado del FORMAT y fuerza SVG, que es lo unico
    que ese extremo acepta: `image/png` devuelve 400."""
    url = url.replace("%252F", "%2F").replace("%252B", "%2B")
    if "FORMAT=" not in url.upper():
        url += "&FORMAT=image%2Fsvg%2Bxml"
    return url


def _pinned(xml, var, ds_hint):
    """La capa de un dataset CONCRETO, con su estilo y su leyenda.

    Mismo trabajo que _newest() para una variable, pero sin elegir: aqui el
    dataset lo decide quien escribe PINNED. Devuelve None si no esta, y quien
    llame lo cuenta como ausente en vez de callarse.
    """
    for m in re.finditer(r"<Layer[^>]*>(.*?)</Layer>", xml, re.S):
        blk = m.group(1)
        im = re.search(r"<ows:Identifier>([^<]+)</ows:Identifier>", blk)
        if not im or im.group(1).count("/") != 2:
            continue
        ident = im.group(1)
        _, ds, v = ident.split("/")
        if v != var or ds_hint not in ds:
            continue
        tdim = _parse_time_dim(blk)
        cands = []
        for sm in re.finditer(r"<Style([^>]*)>(.*?)</Style>", blk, re.S):
            sid = re.search(r"<ows:Identifier>([^<]+)</ows:Identifier>", sm.group(2))
            if not sid or "logScale" in sid.group(1):
                continue
            lm = re.search(r'<LegendURL[^>]*xlink:href="([^"]+)"', sm.group(2))
            cands.append((sid.group(1),
                          _fix_legend(html.unescape(lm.group(1))) if lm else None))
        style, legend = "", None
        if cands:
            pick = (next((c for c in cands if "solidAndVector" in c[0]), None)
                    or next((c for c in cands if "vectorStyle:solid" in c[0]), None)
                    or cands[0])
            style, legend = pick
        tm = re.search(r"<ows:Title>([^<]*)</ows:Title>", blk)
        title = tm.group(1) if tm else ""
        return {"dataset_tag": ds.rsplit("_", 1)[-1], "layer": ident, "dataset": ds,
                "title": title.split(" - ", 1)[-1] if " - " in title else title,
                "style": style or "", "legend": legend,
                "step_s": (tdim or {}).get("step_s"), "time": tdim}
    return None


def catalogue(refresh=False):
    """Devuelve (dict listo para el visor, stats)."""
    caps, raw_caps, layers = {}, {}, []
    st = {"products": 0, "from_cache": True}
    for key, pid in PRODUCTS.items():
        xml, cached = _capabilities(pid, refresh=refresh)
        raw_caps[key] = xml
        caps[key] = _newest(xml)
        st["products"] += 1
        st["from_cache"] = st["from_cache"] and cached
        LOG.info("%s: %d variables", pid, len(caps[key]))

    missing = []
    for pkey, var, group, name, why in CURATED:
        hit = caps.get(pkey, {}).get(var)
        if not hit:
            missing.append("%s/%s" % (pkey, var))
            continue
        ident = hit["layer"]
        # El estilo va TAMBIEN en la tesela: si la leyenda es de una paleta y
        # el mosaico de otra, la escala miente, que es peor que no tenerla.
        layers.append({
            "id": "cmems_%s_%s" % (pkey, var),
            "layer": ident, "product": PRODUCTS[pkey], "variable": var,
            "dataset_tag": hit["dataset_tag"], "group": group, "name": name,
            "title": hit["title"], "why": why, "style": hit["style"],
            "producer": PRODUCERS.get(pkey),
            "res_km": GLOBAL_RES_KM if pkey == "glob" else BALTIC_RES_KM,
            # La ventana temporal que DECLARA el servicio. Alimenta el carril
            # de la linea de tiempo: sin ella no se puede saber de un vistazo
            # si dos capas tienen dato en el mismo instante.
            "step_s": hit.get("step_s") if hit.get("step_s", 10 ** 9) < 10 ** 9 else None,
            "time": ({"start_ms": _iso_ms(hit["time"]["start"]),
                      "end_ms": _iso_ms(hit["time"]["end"]),
                      "start": hit["time"]["start"], "end": hit["time"]["end"],
                      "step_s": hit["time"]["step_s"],
                      "instants": hit["time"]["instants"]}
                     if hit.get("time") else None),
            "template": (WMTS + "?service=WMTS&version=1.0.0&request=GetTile"
                         "&layer=" + ident + "&style=" + hit["style"] +
                         "&tilematrixset=EPSG:3857"
                         "&TileMatrix={z}&TileRow={y}&TileCol={x}"
                         "&format=image/png"),
            "legend": hit["legend"],
        })
    # Las capas atadas a un dataset concreto. Van detras y en su propio grupo:
    # son contraste, no fuente principal, y mezclarlas con el modelo baltico
    # invitaria a compararlas como si fueran lo mismo.
    for pkey, var, ds_hint, group, name, why in PINNED:
        hit = _pinned(raw_caps.get(pkey, ""), var, ds_hint)
        if not hit:
            missing.append("%s/%s@%s" % (pkey, var, ds_hint))
            continue
        layers.append({
            "id": "cmems_%s_%s_%s" % (pkey, ds_hint.replace("-", ""), var),
            "layer": hit["layer"], "product": PRODUCTS[pkey], "variable": var,
            "dataset_tag": hit["dataset_tag"], "group": group, "name": name,
            "title": hit["title"], "why": why, "style": hit["style"],
            "producer": PRODUCERS.get(pkey),
            "res_km": GLOBAL_RES_KM if pkey == "glob" else BALTIC_RES_KM,
            "template": (WMTS + "?service=WMTS&version=1.0.0&request=GetTile"
                         "&layer=" + hit["layer"] + "&style=" + hit["style"] +
                         "&tilematrixset=EPSG:3857"
                         "&TileMatrix={z}&TileRow={y}&TileCol={x}"
                         "&format=image/png"),
            "legend": hit["legend"],
            "step_s": hit.get("step_s"),
            "time": ({"start_ms": _iso_ms(hit["time"]["start"]),
                      "end_ms": _iso_ms(hit["time"]["end"]),
                      "start": hit["time"]["start"], "end": hit["time"]["end"],
                      "step_s": hit["time"]["step_s"],
                      "instants": hit["time"]["instants"]}
                     if hit.get("time") else None),
        })

    st["layers"] = len(layers)
    st["missing"] = missing
    st["with_legend"] = sum(1 for l in layers if l["legend"])
    st["with_time"] = sum(1 for l in layers if l.get("time"))
    st["cadence_s"] = sorted({l["step_s"] for l in layers if l.get("step_s")})
    if missing:
        LOG.warning("variables ausentes del catalogo: %s", ", ".join(missing))
    return {
        "attribution": "E.U. Copernicus Marine Service Information",
        "wmts": WMTS,
        "products": PRODUCTS,
        "producers": PRODUCERS,
        "current_dir_rms_deg": CURRENT_DIR_RMS_DEG,
        "caveat": ("Surface current direction carries an RMS error of %d degrees, "
                   "validated against seven moorings for the whole sea. It supports "
                   "'there was a current', not a computed drift."
                   % CURRENT_DIR_RMS_DEG),
        "layers": layers,
    }, st


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cat, st = catalogue()
    print(json.dumps(st, indent=1))
    g = {}
    for l in cat["layers"]:
        g.setdefault(l["group"], []).append(l)
    for k in sorted(g):
        print("\n%s" % k.upper())
        for l in g[k]:
            print("   %-26s %-14s %-12s %s" % (l["name"][:26], l["variable"][:14],
                                               l["style"], "legend" if l["legend"] else "SIN LEYENDA"))
