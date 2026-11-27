"""Enriquecimiento de buques: qué es, cuánto mide y si está señalado.

TRES NIVELES, Y LA DIFERENCIA IMPORTA
-------------------------------------
1. GRATIS Y SIN RED. Eslora, manga y calado salen del propio mensaje AIS 5:
   referencePointA..D son las distancias de la antena a proa, popa, babor y
   estribor (ITU-R M.1371). Eslora = A+B, manga = C+D, calado = draught/10.
   Esto estaba en el almacén desde el primer día sin que nadie lo usara.
2. GRATIS CON RED, AUTORITATIVO. Listas de sanciones. OFAC SDN publica 1.570
   buques, 1.560 con IMO y 840 con MMSI, en XML estructurado (comprobado el
   2026-11-10). Para un producto de defensa esto vale más que una foto: un
   petrolero sancionado merodeando sobre un cable no es el mismo suceso que
   un ferry haciendo lo mismo.
3. GRATIS CON RED, PARCIAL. Wikidata/Commons para foto y particulares. Cubre
   bien buques notables (ferries, militares, petroleros famosos) y mal el
   mercante corriente. Se usa porque la licencia es limpia y el coste cero,
   no porque sea completo. Lo que no aparezca se dice.

LO QUE NO SE USA Y POR QUE
--------------------------
  Equasis / IHS Sea-web / Lloyd's   Los particulares autoritativos de verdad.
      Equasis es gratis con registro pero NO tiene API y raspar su web va
      contra sus condiciones. Si esto llega a producto, es una licencia que
      hay que pagar, no un scraper que hay que esconder.
  MarineTraffic / VesselFinder      Fotos y particulares excelentes, API de
      pago. VesselFinder tiene plan gratuito muy limitado.
  THETIS-EU / Paris MoU             Historial de inspecciones y detenciones
      por IMO. Público y muy pertinente (una detención reciente cambia la
      lectura de una alerta) pero sin API: formulario web. Pendiente.
  GISIS (OMI)                       Requiere cuenta y no tiene API.

LICENCIAS: OFAC SDN es obra del gobierno de EE. UU., dominio público.
Wikidata es CC0. Las imágenes de Commons llevan cada una la suya y se guarda
el enlace al fichero para poder citarla.
"""
import json
import logging
import re
import xml.etree.ElementTree as ET

from . import net

LOG = logging.getLogger("custody.vesselinfo")

OFAC_SDN = "https://www.treasury.gov/ofac/downloads/sdn.xml"
EU_FSF = ("https://webgate.ec.europa.eu/fsd/fsf/public/files/"
          "xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw")
WIKIDATA = "https://query.wikidata.org/sparql"


# ---------------------------------------------------------------- bandera
# MID (Maritime Identification Digits, UIT-R M.585): las tres primeras cifras
# del MMSI. La tabla vivía en el JavaScript del visor y solo cubría el
# Báltico, así que banderas de conveniencia que SÍ aparecen en el golfo
# salían como «MID 255». Se trae aquí para tener una sola fuente y se emite
# resuelta en vessel_info.json.
#
# Un MMSI es autodeclarado como todo lo demás del AIS y la bandera deducida
# no prueba el pabellón real: prueba qué administración emitió el identificador
# que el buque afirma tener.
MID = {
    "201": "Albania", "202": "Andorra", "203": "Austria", "204": "Portugal (Azores)",
    "205": "Belgium", "206": "Belarus", "207": "Bulgaria", "208": "Vatican",
    "209": "Cyprus", "210": "Cyprus", "211": "Germany", "212": "Cyprus",
    "213": "Georgia", "214": "Moldova", "215": "Malta", "216": "Armenia",
    "218": "Germany", "219": "Denmark", "220": "Denmark", "224": "Spain",
    "225": "Spain", "226": "France", "227": "France", "228": "France",
    "229": "Malta", "230": "Finland", "231": "Faroe Islands", "232": "United Kingdom",
    "233": "United Kingdom", "234": "United Kingdom", "235": "United Kingdom",
    "236": "Gibraltar", "237": "Greece", "238": "Croatia", "239": "Greece",
    "240": "Greece", "241": "Greece", "242": "Morocco", "243": "Hungary",
    "244": "Netherlands", "245": "Netherlands", "246": "Netherlands",
    "247": "Italy", "248": "Malta", "249": "Malta", "250": "Ireland",
    "251": "Iceland", "252": "Liechtenstein", "253": "Luxembourg", "254": "Monaco",
    "255": "Portugal (Madeira)", "256": "Malta", "257": "Norway", "258": "Norway",
    "259": "Norway", "261": "Poland", "262": "Montenegro", "263": "Portugal",
    "264": "Romania", "265": "Sweden", "266": "Sweden", "267": "Slovakia",
    "268": "San Marino", "269": "Switzerland", "270": "Czechia", "271": "Turkey",
    "272": "Ukraine", "273": "Russia", "274": "North Macedonia", "275": "Latvia",
    "276": "Estonia", "277": "Lithuania", "278": "Slovenia", "279": "Serbia",
    "301": "Anguilla", "303": "Alaska (USA)", "304": "Antigua and Barbuda",
    "305": "Antigua and Barbuda", "306": "Curacao / Sint Maarten", "307": "Aruba",
    "308": "Bahamas", "309": "Bahamas", "310": "Bermuda", "311": "Bahamas",
    "312": "Belize", "314": "Barbados", "316": "Canada", "319": "Cayman Islands",
    "321": "Costa Rica", "323": "Cuba", "325": "Dominica",
    "327": "Dominican Republic", "329": "Guadeloupe", "330": "Grenada",
    "331": "Greenland", "332": "Guatemala", "334": "Honduras", "336": "Haiti",
    "338": "United States", "339": "Jamaica", "341": "Saint Kitts and Nevis",
    "343": "Saint Lucia", "345": "Mexico", "347": "Martinique", "348": "Montserrat",
    "350": "Nicaragua", "351": "Panama", "352": "Panama", "353": "Panama",
    "354": "Panama", "355": "Panama", "356": "Panama", "357": "Panama",
    "358": "Puerto Rico", "359": "El Salvador", "361": "Saint Pierre and Miquelon",
    "362": "Trinidad and Tobago", "364": "Turks and Caicos", "366": "United States",
    "367": "United States", "368": "United States", "369": "United States",
    "370": "Panama", "371": "Panama", "372": "Panama", "373": "Panama",
    "374": "Panama", "375": "Saint Vincent and the Grenadines",
    "376": "Saint Vincent and the Grenadines", "377": "Saint Vincent and the Grenadines",
    "378": "British Virgin Islands", "379": "US Virgin Islands",
    "401": "Afghanistan", "403": "Saudi Arabia", "405": "Bangladesh",
    "408": "Bahrain", "410": "Bhutan", "412": "China", "413": "China",
    "414": "China", "416": "Taiwan", "417": "Sri Lanka", "419": "India",
    "422": "Iran", "423": "Azerbaijan", "425": "Iraq", "428": "Israel",
    "431": "Japan", "432": "Japan", "434": "Turkmenistan", "436": "Kazakhstan",
    "437": "Uzbekistan", "438": "Jordan", "440": "South Korea", "441": "South Korea",
    "443": "Palestine", "445": "North Korea", "447": "Kuwait", "450": "Lebanon",
    "451": "Kyrgyzstan", "453": "Macao", "455": "Maldives", "457": "Mongolia",
    "459": "Nepal", "461": "Oman", "463": "Pakistan", "466": "Qatar",
    "468": "Syria", "470": "United Arab Emirates", "471": "United Arab Emirates",
    "472": "Tajikistan", "473": "Yemen", "475": "Yemen", "477": "Hong Kong",
    "478": "Bosnia and Herzegovina", "501": "Adelie Land", "503": "Australia",
    "506": "Myanmar", "508": "Brunei", "510": "Micronesia", "511": "Palau",
    "512": "New Zealand", "514": "Cambodia", "515": "Cambodia", "516": "Christmas Island",
    "518": "Cook Islands", "520": "Fiji", "523": "Cocos Islands",
    "525": "Indonesia", "529": "Kiribati", "531": "Laos", "533": "Malaysia",
    "536": "Northern Mariana Islands", "538": "Marshall Islands", "540": "New Caledonia",
    "542": "Niue", "544": "Nauru", "546": "French Polynesia", "548": "Philippines",
    "553": "Papua New Guinea", "555": "Pitcairn", "557": "Solomon Islands",
    "559": "American Samoa", "561": "Samoa", "563": "Singapore", "564": "Singapore",
    "565": "Singapore", "566": "Singapore", "567": "Thailand", "570": "Tonga",
    "572": "Tuvalu", "574": "Vietnam", "576": "Vanuatu", "577": "Vanuatu",
    "578": "Wallis and Futuna", "601": "South Africa", "603": "Angola",
    "605": "Algeria", "607": "Saint Paul and Amsterdam", "608": "Ascension",
    "609": "Burundi", "610": "Benin", "611": "Botswana", "612": "Central African Rep.",
    "613": "Cameroon", "615": "Congo", "616": "Comoros", "617": "Cabo Verde",
    "618": "Crozet", "619": "Cote d'Ivoire", "620": "Comoros", "621": "Djibouti",
    "622": "Egypt", "624": "Ethiopia", "625": "Eritrea", "626": "Gabon",
    "627": "Ghana", "629": "Gambia", "630": "Guinea-Bissau", "631": "Equatorial Guinea",
    "632": "Guinea", "633": "Burkina Faso", "634": "Kenya", "635": "Kerguelen",
    "636": "Liberia", "637": "Liberia", "638": "South Sudan", "642": "Libya",
    "644": "Lesotho", "645": "Mauritius", "647": "Madagascar", "649": "Mali",
    "650": "Mozambique", "654": "Mauritania", "655": "Malawi", "656": "Niger",
    "657": "Nigeria", "659": "Namibia", "660": "Reunion", "661": "Rwanda",
    "662": "Sudan", "663": "Senegal", "664": "Seychelles", "665": "Saint Helena",
    "666": "Somalia", "667": "Sierra Leone", "668": "Sao Tome and Principe",
    "669": "Eswatini", "670": "Chad", "671": "Togo", "672": "Tunisia",
    "674": "Tanzania", "675": "Uganda", "676": "DR Congo", "677": "Tanzania",
    "678": "Zambia", "679": "Zimbabwe", "701": "Argentina", "710": "Brazil",
    "720": "Bolivia", "725": "Chile", "730": "Colombia", "735": "Ecuador",
    "740": "Falkland Islands", "745": "French Guiana", "750": "Guyana",
    "755": "Paraguay", "760": "Peru", "765": "Suriname", "770": "Uruguay",
    "775": "Venezuela",
}
# Prefijos que no son buques y que conviene no etiquetar como bandera.
MMSI_SPECIAL = {"00": "coast station", "99": "aid to navigation",
                "98": "auxiliary craft", "97": "SAR / distress", "111": "SAR aircraft"}


def flag_of(mmsi):
    m = str(mmsi)
    for pref, what in MMSI_SPECIAL.items():
        if m.startswith(pref):
            return {"flag": None, "mmsi_kind": what, "mid": m[:3]}
    return {"flag": MID.get(m[:3]), "mmsi_kind": "ship", "mid": m[:3]}


# --------------------------------------------------------------- tipo AIS
# ITU-R M.1371 tabla 53. La primera cifra es la familia; la segunda, detalle
# de carga peligrosa que aquí no se usa para clasificar.
FAMILY = {
    2: ("wig", "Wing in ground"),
    3: ("special", "Special craft"),
    4: ("hsc", "High-speed craft"),
    5: ("service", "Service craft"),
    6: ("passenger", "Passenger"),
    7: ("cargo", "Cargo"),
    8: ("tanker", "Tanker"),
    9: ("other", "Other"),
}
# Los del bloque 3x son heterogéneos y algunos importan mucho por separado.
SPECIAL = {30: ("fishing", "Fishing"), 31: ("service", "Towing"),
           32: ("service", "Towing (large)"), 33: ("service", "Dredger"),
           34: ("service", "Diving ops"), 35: ("military", "Military ops"),
           36: ("sailing", "Sailing"), 37: ("pleasure", "Pleasure craft")}
SERVICE = {50: "Pilot", 51: "Search and rescue", 52: "Tug", 53: "Port tender",
           54: "Anti-pollution", 55: "Law enforcement", 58: "Medical transport"}

# Eslora en metros. Los cortes no son arbitrarios: 25 m separa la embarcación
# menor del buque; 100 m el costero del de altura; 200 m es donde empiezan los
# Aframax y los portacontenedores grandes, que son los que arrastran un ancla
# capaz de romper un cable.
SIZE_BANDS = [(25, "small"), (100, "coastal"), (200, "large"), (1e9, "very_large")]


def dimensions(v):
    """Eslora, manga y calado desde el mensaje AIS estático. Sin red."""
    a, b = v.get("referencePointA"), v.get("referencePointB")
    c, d = v.get("referencePointC"), v.get("referencePointD")
    out = {}
    if isinstance(a, int) and isinstance(b, int) and (a + b) > 0:
        out["length_m"] = a + b
    if isinstance(c, int) and isinstance(d, int) and (c + d) > 0:
        out["beam_m"] = c + d
    dr = v.get("draught")
    if isinstance(dr, int) and dr > 0:
        out["draught_m"] = dr / 10.0
    if "length_m" in out and "beam_m" in out and out["beam_m"]:
        out["loa_beam_ratio"] = round(out["length_m"] / out["beam_m"], 2)
    return out


def size_class(length_m):
    if not length_m:
        return None
    for lim, name in SIZE_BANDS:
        if length_m < lim:
            return name
    return "very_large"


def classify(v, dims=None):
    """Familia, subtipo y clase de tamaño. Todo derivado del AIS."""
    st = v.get("shipType")
    fam, label = "unknown", "Unknown"
    if isinstance(st, int):
        if st in SPECIAL:
            fam, label = SPECIAL[st]
        elif st in SERVICE:
            fam, label = "service", SERVICE[st]
        elif st // 10 in FAMILY:
            fam, label = FAMILY[st // 10]
    dims = dims if dims is not None else dimensions(v)
    out = {"family": fam, "type_label": label, "ais_type": st,
           "size_class": size_class(dims.get("length_m"))}
    # Autodeclarado y falsificable. Se MARCA, nunca se filtra: justo los que
    # mienten sobre su tipo son los que interesan.
    out["self_declared"] = True
    out["military_or_service"] = fam in ("military", "service")
    return out


# ------------------------------------------------------------- sanciones
def _txt(e, path):
    return (e.findtext(path) or "").strip()


def ofac_vessels(refresh=False):
    """{imo: registro} y {mmsi: registro} desde OFAC SDN. Dominio público."""
    raw, cached = net.fetch(OFAC_SDN, refresh=refresh, timeout=300, ext="xml")
    root = ET.fromstring(raw)
    by_imo, by_mmsi, n = {}, {}, 0
    for e in root:
        if e.tag.split("}")[-1] != "sdnEntry":
            continue
        if _txt(e, "{*}sdnType") != "Vessel":
            continue
        n += 1
        rec = {
            "list": "OFAC SDN",
            "name": _txt(e, "{*}lastName"),
            "programs": [p.text for p in e.findall(".//{*}program") if p.text],
            "vessel_type": _txt(e, ".//{*}vesselType") or None,
            "flag": _txt(e, ".//{*}vesselFlag") or None,
            "owner": _txt(e, ".//{*}vesselOwner") or None,
            "grt": _txt(e, ".//{*}grossRegisteredTonnage") or None,
            "call_sign": _txt(e, ".//{*}callSign") or None,
            "aka": [a.strip() for a in
                    (_txt(x, "{*}lastName") for x in e.findall(".//{*}aka")) if a.strip()],
            "uid": _txt(e, "{*}uid"),
        }
        imos, mmsis = [], []
        for i in e.findall(".//{*}id"):
            ty = _txt(i, "{*}idType")
            num = _txt(i, "{*}idNumber")
            if not num:
                continue
            if "Vessel Registration" in ty or ty.upper().startswith("IMO"):
                m = re.search(r"(\d{7})", num)
                if m:
                    imos.append(m.group(1))
            elif ty.upper() == "MMSI":
                m = re.search(r"(\d{9})", num)
                if m:
                    mmsis.append(m.group(1))
        rec["imo"] = imos[0] if imos else None
        for x in imos:
            by_imo[x] = rec
        for x in mmsis:
            by_mmsi[x] = rec
    LOG.info("OFAC SDN: %d buques, %d con IMO, %d con MMSI (cache=%s)",
             n, len(by_imo), len(by_mmsi), cached)
    return by_imo, by_mmsi, {"vessels": n, "by_imo": len(by_imo),
                             "by_mmsi": len(by_mmsi), "from_cache": cached}


def eu_vessel_imos(refresh=False):
    """IMOs citados en la lista consolidada de la UE.

    La UE NO tipifica buques como sujeto: los IMO aparecen dentro del texto
    libre de `remark`. Se extraen con expresión regular y se marcan como
    CONFIANZA BAJA, porque un número de siete cifras en prosa puede no ser un
    IMO y la asociación con la entidad sancionada es indirecta. Es una pista
    para mirar, no una determinación.
    """
    raw, cached = net.fetch(EU_FSF, refresh=refresh, timeout=300, ext="xml")
    txt = raw.decode("utf-8", "replace")
    out = {}
    for m in re.finditer(r"IMO[^.;]{0,80}?(\d{7})", txt):
        ctx = txt[max(0, m.start() - 200):m.end() + 80]
        ctx = re.sub(r"<[^>]+>", " ", ctx)
        out[m.group(1)] = {"list": "EU consolidated", "confidence": "low",
                           "context": re.sub(r"\s+", " ", ctx).strip()[-260:]}
    LOG.info("UE: %d IMO citados en texto libre (cache=%s)", len(out), cached)
    return out, {"imos": len(out), "from_cache": cached, "confidence": "low"}


# -------------------------------------------------------------- Wikidata
WD_QUERY = """SELECT ?imo ?item ?itemLabel ?img ?len ?beam ?gt ?dwt ?built ?article WHERE {
  VALUES ?imo { %s }
  ?item wdt:P458 ?imo .
  OPTIONAL { ?item wdt:P18    ?img }
  OPTIONAL { ?item wdt:P2043  ?len }
  OPTIONAL { ?item wdt:P2261  ?beam }
  OPTIONAL { ?item wdt:P1093  ?gt }
  OPTIONAL { ?item wdt:P1543  ?dwt }
  OPTIONAL { ?item wdt:P729   ?built }
  OPTIONAL { ?article schema:about ?item ;
             schema:isPartOf <https://en.wikipedia.org/> }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,fi,sv,es" }
}"""


def wikidata(imos, refresh=False, batch=120):
    """IMO -> {label, image, length_m, beam_m, gt, dwt, built, wikipedia}.

    Wikidata es CC0 y no pide clave. La cobertura del mercante corriente es
    baja: aquí se trata como adorno útil, no como fuente de particulares.
    """
    imos = [str(i) for i in imos if i]
    out, st = {}, {"asked": len(imos), "found": 0, "with_image": 0, "errors": 0}
    for k in range(0, len(imos), batch):
        chunk = imos[k:k + batch]
        q = WD_QUERY % " ".join('"%s"' % i for i in chunk)
        url = WIKIDATA + "?format=json&query=" + net.urllib.parse.quote(q)
        try:
            raw, _c = net.fetch(url, headers={"Accept": "application/sparql-results+json"},
                                refresh=refresh, timeout=180, ext="json")
            doc = json.loads(raw.decode("utf-8"))
        except Exception as exc:                        # noqa: BLE001
            st["errors"] += 1
            LOG.warning("Wikidata lote %d: %s", k // batch, str(exc)[:140])
            continue
        for b in doc.get("results", {}).get("bindings", []):
            imo = b["imo"]["value"]
            rec = out.setdefault(imo, {})
            lab = b.get("itemLabel", {}).get("value")
            # Un label que es el propio Q-id significa ficha vacía.
            if lab and not re.fullmatch(r"Q\d+", lab):
                rec["label"] = lab
            if "img" in b:
                rec["image"] = b["img"]["value"]
            for key, fld in (("len", "length_m"), ("beam", "beam_m"),
                             ("gt", "gross_tonnage"), ("dwt", "deadweight_t")):
                if key in b:
                    try:
                        rec[fld] = float(b[key]["value"])
                    except ValueError:
                        pass
            if "built" in b:
                rec["built"] = b["built"]["value"][:10]
            if "article" in b:
                rec["wikipedia"] = b["article"]["value"]
            rec["source"] = "Wikidata (CC0) · image via Wikimedia Commons"
    st["found"] = len(out)
    st["with_image"] = sum(1 for v in out.values() if v.get("image"))
    LOG.info("Wikidata: %d/%d encontrados, %d con foto", st["found"], st["asked"],
             st["with_image"])
    return out, st


# --------------------------------------------------------------- dossier
def build(vessels, use_net=True, refresh=False, wikidata_limit=400):
    """mmsi -> dossier. `vessels` es el dict de ais.load_vessels()."""
    out, stats = {}, {}
    for mmsi, v in vessels.items():
        dims = dimensions(v)
        rec = {"mmsi": mmsi, "imo": v.get("imo") or None,
               "name": (v.get("name") or "").strip() or None,
               "call_sign": (v.get("callSign") or "").strip() or None,
               "dimensions": dims, "class": classify(v, dims)}
        rec.update(flag_of(mmsi))
        out[str(mmsi)] = rec

    if not use_net:
        stats["net"] = "omitido (--skip-net)"
        return out, stats

    try:
        by_imo, by_mmsi, st = ofac_vessels(refresh=refresh)
        stats["ofac"] = st
        hits = 0
        for k, rec in out.items():
            hit = by_mmsi.get(k) or (by_imo.get(str(rec["imo"])) if rec["imo"] else None)
            if hit:
                rec["sanctions"] = [dict(hit, matched_on="MMSI" if k in by_mmsi else "IMO")]
                hits += 1
        stats["ofac"]["matched_in_aoi"] = hits
    except Exception as exc:                            # noqa: BLE001
        stats["ofac"] = {"error": str(exc)[:200]}
        LOG.warning("OFAC: %s", str(exc)[:160])

    try:
        eu, st = eu_vessel_imos(refresh=refresh)
        stats["eu_sanctions"] = st
        hits = 0
        for rec in out.values():
            if rec["imo"] and str(rec["imo"]) in eu:
                rec.setdefault("sanctions", []).append(
                    dict(eu[str(rec["imo"])], matched_on="IMO"))
                hits += 1
        stats["eu_sanctions"]["matched_in_aoi"] = hits
    except Exception as exc:                            # noqa: BLE001
        stats["eu_sanctions"] = {"error": str(exc)[:200]}
        LOG.warning("UE: %s", str(exc)[:160])

    try:
        # Primero los grandes: son los que pueden romper un cable y también
        # los que Wikidata cubre mejor.
        cand = sorted((r for r in out.values() if r["imo"]),
                      key=lambda r: -(r["dimensions"].get("length_m") or 0))
        wd, st = wikidata([r["imo"] for r in cand[:wikidata_limit]], refresh=refresh)
        stats["wikidata"] = st
        for rec in out.values():
            if rec["imo"] and str(rec["imo"]) in wd:
                rec["reference"] = wd[str(rec["imo"])]
    except Exception as exc:                            # noqa: BLE001
        stats["wikidata"] = {"error": str(exc)[:200]}
        LOG.warning("Wikidata: %s", str(exc)[:160])

    return out, stats
