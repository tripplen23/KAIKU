"""
orbitas_def.py — catalogo de las seis familias orbitales candidatas (D10)
y de los emplazamientos de interes.

Cada orbita se define por parametros fisicos verificables, no por eslogan.
Las HEO se sintonizan en RAAN para que el apogeo (o el primer apogeo, en TAP)
caiga sobre la longitud de referencia LON_REF.
"""

import math
from orbital import (MU, RE, J2, OMEGA_E, T_SID, DEG, RAD,
                     Orbit, period, sma_from_period)

LON_REF = 25.0   # deg E — meridiano central de Finlandia / Golfo de Finlandia

# ------------------------------------------------------------------ sitios
SITES = {
    "GoF":      (59.80, 25.50, "Golfo de Finlandia, centro (59-61 N)"),
    "Helsinki": (60.17, 24.94, "Helsinki"),
    "Hanko":    (59.50, 22.50, "Hanko / boca del Golfo, cables Estlink"),
    "Utsjoki":  (69.91, 27.03, "Utsjoki, frontera norte"),
    "Barents":  (72.00, 30.00, "Mar de Barents, limite norte de interes"),
}

# Area de responsabilidad ALTO NORTE (revision 28-oct-2026).
# Motivo: Product & Market documenta que la custodia continua del Golfo de
# Finlandia ya la presta GOFREP desde tierra (radar + AIS, 24 h,
# IMO MSC.139(76)). El hueco para orbita alta esta donde GOFREP no llega.
SITES_NORTE = {
    "Barents-C":  (73.00, 30.00, "Mar de Barents central"),
    "Kola":       (70.00, 35.00, "Aproximaciones a Kola / Varanger"),
    "Noruega":    (68.00, 10.00, "Mar de Noruega, rutas del Alto Norte"),
    "Svalbard-S": (76.00, 18.00, "Sur de Svalbard"),
    "Fram":       (78.00,  5.00, "Estrecho de Fram / borde de hielo"),
    "GoF":        (59.80, 25.50, "Golfo de Finlandia (referencia heredada)"),
}
SITE_PRIMARY = "GoF"


# ------------------------------------------------------------------ SSO
def sso_inclination(a, e=0.0):
    """Inclinacion heliosincrona exacta para (a,e) dados, con J2 secular."""
    n = math.sqrt(MU / a ** 3)
    p = a * (1 - e ** 2)
    target = 2 * math.pi / 365.2422 / 86400.0      # rad/s
    ci = -target / (1.5 * J2 * (RE / p) ** 2 * n)
    return math.acos(ci) * RAD


# ------------------------------------------------------------------ tuner
def tune_raan_apogee(orb, lon_target=LON_REF):
    """Devuelve copia con RAAN tal que el subpunto en apogeo este en lon_target."""
    t_apo = (math.pi - orb.M0) / orb.dM
    lat, lon, _ = orb.subpoint(t_apo, gmst0=0.0)
    return orb.copy_with(raan_deg=(orb.raan0 * RAD + (lon_target - lon)) % 360.0)


# ------------------------------------------------------------------ catalogo
def build():
    O = {}

    # 1. LEO SSO 600 km — la referencia del mercado (ICEYE, Planet, OroraTech)
    a = RE + 600.0
    O["LEO-SSO-600"] = Orbit("LEO-SSO-600", a, 0.0, sso_inclination(a),
                             0.0, 0.0, 0.0,
                             label="LEO SSO 600 km (i=%.2f)" % sso_inclination(a))

    # 1b. LEO SSO 500 km — extremo inferior del rango pedido
    a = RE + 500.0
    O["LEO-SSO-500"] = Orbit("LEO-SSO-500", a, 0.0, sso_inclination(a),
                             0.0, 0.0, 0.0, label="LEO SSO 500 km")

    # 1c. LEO polar 700 km
    a = RE + 700.0
    O["LEO-SSO-700"] = Orbit("LEO-SSO-700", a, 0.0, sso_inclination(a),
                             0.0, 0.0, 0.0, label="LEO SSO 700 km")

    # 2. LEO alta 2000 km, i=63.4 (nucleo del cinturon de protones interno)
    O["LEO-ALTA-2000"] = Orbit("LEO-ALTA-2000", RE + 2000.0, 0.0, 63.435,
                               0.0, 0.0, 0.0, label="LEO alta 2.000 km i=63.4")

    # 3. MEO 8.000 km, i=63.4
    O["MEO-8000"] = Orbit("MEO-8000", RE + 8000.0, 0.0, 63.435,
                          0.0, 0.0, 0.0, label="MEO 8.000 km i=63.4")

    # 3b. MEO 20.000 km, i=63.4 (misma energia que Molniya, circular)
    O["MEO-20000"] = Orbit("MEO-20000", RE + 20000.0, 0.0, 63.435,
                           0.0, 0.0, 0.0, label="MEO 20.000 km i=63.4")

    # 4. GEO a 25 E (caso optimo para Finlandia; los slots reales son otra cosa)
    O["GEO-25E"] = Orbit("GEO-25E", sma_from_period(T_SID), 0.0, 0.0,
                         LON_REF, 0.0, 0.0, label="GEO 35.786 km @25 E")
    # 4b. GEO a 0 E — slot europeo plausible
    O["GEO-0E"] = Orbit("GEO-0E", sma_from_period(T_SID), 0.0, 0.0,
                        0.0, 0.0, 0.0, label="GEO 35.786 km @0 E")

    # 5. Molniya 12 h (T = medio dia sidereo), perigeo 600 km, i critica
    a = sma_from_period(T_SID / 2.0)
    e = 1.0 - (RE + 600.0) / a
    O["MOLNIYA"] = tune_raan_apogee(
        Orbit("MOLNIYA", a, e, 63.435, 0.0, 270.0, 0.0,
              label="Molniya 12 h, hp=600 km, i=63.4"))

    # 6. Tundra 24 h (T = dia sidereo), e=0.25, i critica
    a = sma_from_period(T_SID)
    O["TUNDRA"] = tune_raan_apogee(
        Orbit("TUNDRA", a, 0.25, 63.435, 0.0, 270.0, 0.0,
              label="Tundra 24 h, e=0.25, i=63.4"))
    O["TUNDRA-e20"] = tune_raan_apogee(
        Orbit("TUNDRA-e20", a, 0.20, 63.435, 0.0, 270.0, 0.0,
              label="Tundra 24 h, e=0.20"))
    O["TUNDRA-e30"] = tune_raan_apogee(
        Orbit("TUNDRA-e30", a, 0.30, 63.435, 0.0, 270.0, 0.0,
              label="Tundra 24 h, e=0.30"))

    # 7. TAP / Three-Apogee 16 h — parametros ASBM publicados
    #    apogeo 43.500 km, perigeo 8.100 km (altitudes), i=65
    ra, rp = RE + 43500.0, RE + 8100.0
    a = 0.5 * (ra + rp)
    e = (ra - rp) / (ra + rp)
    O["TAP-ASBM"] = tune_raan_apogee(
        Orbit("TAP-ASBM", a, e, 65.0, 0.0, 270.0, 0.0,
              label="TAP 16 h (ASBM): 8.100 x 43.500 km, i=65"))

    return O


# conjunto principal que entra en la tabla de decision
MAIN = ["LEO-SSO-600", "LEO-ALTA-2000", "MEO-8000", "MEO-20000",
        "GEO-25E", "MOLNIYA", "TUNDRA", "TAP-ASBM"]

if __name__ == "__main__":
    for k, o in build().items():
        print("%-14s a=%9.1f e=%.4f i=%6.2f T=%7.3f h  hp=%8.1f ha=%8.1f "
              "dRAAN=%+7.3f deg/dia dargp=%+7.3f deg/dia"
              % (k, o.a, o.e, o.i * RAD, o.T / 3600.0,
                 o.rp - RE, o.ra - RE,
                 o.draan * RAD * 86400, o.dargp * RAD * 86400))
