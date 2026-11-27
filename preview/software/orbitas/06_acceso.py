"""
06_acceso.py  (D10.6)
Coste de acceso: delta-v desde GTO, penalizacion de azimut de lanzamiento,
fraccion de propulsante, y cruce de la region protegida GEO.

Delta-v GTO -> orbita objetivo, dos impulsos:
  1) en el apogeo de la GTO (r = 42.164 km): quemada combinada que
     (a) gira el plano Delta_i y (b) lleva el apogeo a r_a del objetivo.
     El cambio de plano gira la componente transversal; la radial no.
       dV1^2 = (v2r - v1r)^2 + v1t^2 + v2t^2 - 2 v1t v2t cos(Delta_i)
  2) en el nuevo apogeo: ajuste de perigeo (coaxial, impulso transversal).
Es una cota INFERIOR: ignora perdidas por empuje finito, correcciones y
desviacion del argumento del perigeo. Un presupuesto real anade 5-10%.
[CALCULADO + SUPUESTO en el margen]

Region protegida GEO (IADC/ISO 24113): altitud 35.786 +/- 200 km y
latitud +/- 15 deg. Se calcula en que latitud cada orbita cruza r = 42.164 km.

Salida: resultados/06_acceso.md
"""
import math
from orbital import MU, RE, RAD, DEG, sma_from_period, T_SID, md_table
import orbitas_def as od

G0 = 9.80665

GTO = {  # nombre: (h_perigeo, h_apogeo, inclinacion)
    "GTO Kourou (Ariane 6), i=6": (250.0, 35786.0, 6.0),
    "GTO Cabo Canaveral (F9), i=27": (185.0, 35786.0, 27.0),
}

SITES_LAUNCH = {
    "Kourou (CSG)": 5.24,
    "Cabo Canaveral": 28.49,
    "Vandenberg": 34.74,
    "Andoya (NO)": 69.29,
    "Esrange (SE)": 67.89,
}

ISP = {"Biprop apogeo (Isp=321 s)": 321.0,
       "Electrico (Isp=1600 s)": 1600.0}

orbs = od.build()
ORDER = od.MAIN


def vis_viva(r, a):
    return math.sqrt(MU * (2.0 / r - 1.0 / a))


def state_at(r, rp, ra):
    """(v, vt, vr) [km/s] a radio r en la orbita (rp, ra)."""
    a = 0.5 * (rp + ra)
    p = 2.0 * rp * ra / (rp + ra)
    v = math.sqrt(max(MU * (2.0 / r - 1.0 / a), 0.0))
    vt = math.sqrt(MU * p) / r
    vt = min(vt, v)
    vr = math.sqrt(max(v * v - vt * vt, 0.0))
    return v, vt, vr


def burn(r, orb_a, orb_b, dinc_rad):
    """dV [km/s] de una quemada a radio r entre dos orbitas coplanares-salvo-
    el-giro dinc. El giro de plano es alrededor del vector radio: la componente
    radial no rota, la transversal si."""
    _, vt1, vr1 = state_at(r, *orb_a)
    _, vt2, vr2 = state_at(r, *orb_b)
    return math.sqrt((vr2 - vr1) ** 2 + vt1 ** 2 + vt2 ** 2
                     - 2 * vt1 * vt2 * math.cos(dinc_rad))


def dv_gto(rp0, ra0, i0_deg, rp1, ra1, i1_deg, nsplit=181):
    """dV total [m/s] GTO -> objetivo, dos impulsos, repartiendo el cambio de
    plano entre ambos de forma optima (barrido sobre el reparto).
    Quemada 1 en el apsis de la GTO desde el que se ajusta el apogeo;
    quemada 2 en el apogeo final, donde se ajusta el perigeo."""
    di = abs(i1_deg - i0_deg) * DEG
    gto = (rp0, ra0)
    inter = (min(rp0, ra1), max(rp0, ra1))
    final = (min(rp1, ra1), max(rp1, ra1))
    r1 = ra0 if ra1 >= ra0 else rp0
    r2 = max(ra1, rp0) if ra1 >= rp0 else ra1
    best = None
    for k in range(nsplit):
        d1 = di * k / (nsplit - 1)
        d2 = di - d1
        tot = burn(r1, gto, inter, d1) + burn(r2, inter, final, d2)
        if best is None or tot < best[0]:
            best = (tot, burn(r1, gto, inter, d1), burn(r2, inter, final, d2),
                    d1 * RAD)
    return best[1] * 1000.0, best[2] * 1000.0, best[0] * 1000.0, best[3]


def launch_azimuth(lat_deg, inc_deg):
    s = math.cos(inc_deg * DEG) / math.cos(lat_deg * DEG)
    if abs(s) > 1:
        return None
    return math.asin(s) * RAD


def rot_loss(lat_deg, inc_deg):
    """Perdida de beneficio de rotacion terrestre frente al lanzamiento
    directo al este desde el mismo sitio [m/s]."""
    A = launch_azimuth(lat_deg, inc_deg)
    if A is None:
        return None
    veq = 465.1 * math.cos(lat_deg * DEG)
    return veq * (1.0 - math.sin(A * DEG))


def lat_at_r(orb, r_target):
    """Latitudes (deg) en las que la orbita cruza el radio r_target."""
    p = orb.a * (1 - orb.e ** 2)
    if orb.e < 1e-9:
        return None
    cnu = (p / r_target - 1.0) / orb.e
    if abs(cnu) > 1:
        return None
    nu = math.acos(cnu)
    lats = []
    for s in (+1, -1):
        u = orb.argp0 + s * nu
        lats.append(math.asin(math.sin(orb.i) * math.sin(u)) * RAD)
    return lats


out = ["# 06 — Coste de acceso  (D10.6)\n"]

# ---------------- delta-v
for gname, (hp0, ha0, i0) in GTO.items():
    rows = []
    for k in ORDER:
        o = orbs[k]
        d1, d2, dt, sp = dv_gto(RE + hp0, RE + ha0, i0, o.rp, o.ra, o.i * RAD)
        r = [o.label, "%.1f" % (o.i * RAD),
             "%.0f" % d1, "%.0f" % d2, "%.0f" % dt, "%.1f" % sp]
        for iname, isp in ISP.items():
            mf = 1.0 - math.exp(-dt / (isp * G0))
            r.append("%.1f" % (100 * mf))
        rows.append(r)
    out.append("\n## Delta-v desde %s [m/s]\n" % gname)
    out.append(md_table(["Orbita", "i objetivo [deg]", "dV1 (apogeo GTO)",
                         "dV2 (apogeo final)", "dV total",
                         "giro de plano en dV1 [deg]",
                         "% masa de propulsante, Isp=321 s",
                         "% masa de propulsante, Isp=1600 s"], rows))

out.append("\nNota: para LEO SSO la columna no tiene sentido operativo "
           "—nadie va a LEO desde una GTO—; se incluye solo para que la "
           "comparacion sea completa. El acceso real a LEO SSO es un rideshare "
           "directo.\n")

# ---------------- azimut de lanzamiento
rows = []
for sname, lat in SITES_LAUNCH.items():
    r = [sname, "%.2f" % lat]
    for inc in (63.435, 65.0, 97.8):
        A = launch_azimuth(lat, inc)
        L = rot_loss(lat, inc)
        r.append("no alcanzable" if A is None else
                 "Az=%.1f deg, perdida rot. %.0f m/s" % (A, L))
    rows.append(r)
out.append("\n## Azimut de lanzamiento y perdida de beneficio de rotacion\n")
out.append("Condicion directa: cos(i) = cos(lat) * sin(Az). La perdida es "
           "frente a un lanzamiento al este desde el mismo sitio. [CALCULADO]\n")
out.append(md_table(["Base", "latitud [deg]", "i=63,4 (Molniya/Tundra)",
                     "i=65 (TAP/ASBM)", "i=97,8 (SSO)"], rows))

# ---------------- region protegida GEO
R_GEO = sma_from_period(T_SID)
rows = []
for k in ORDER:
    o = orbs[k]
    if o.ra < R_GEO - 200 or o.rp > R_GEO + 200:
        rows.append([o.label, "no cruza", "-", "no"])
        continue
    if o.e < 1e-9:
        rows.append([o.label, "orbita circular EN la region", "0,0", "si"])
        continue
    lats = lat_at_r(o, R_GEO)
    inside = any(abs(l) <= 15.0 for l in lats)
    rows.append([o.label, "si",
                 " / ".join("%.1f" % l for l in lats),
                 "**SI**" if inside else "no"])
out.append("\n## Cruce de la region protegida GEO (35.786 +/- 200 km, "
           "lat +/- 15 deg)\n")
out.append("Definicion IADC / ISO 24113. Un cruce dentro de la region obliga a "
           "cribado de conjuncion continuo, a presupuesto de maniobra y "
           "complica el expediente de licencia y la ITU. [CALCULADO]\n")
out.append(md_table(["Orbita", "cruza r=42.164 km",
                     "latitud del cruce [deg]",
                     "dentro de la region protegida"], rows))

txt = "\n".join(out) + "\n"
open("resultados/06_acceso.md", "w").write(txt)
print(txt)
