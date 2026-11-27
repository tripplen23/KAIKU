"""
08_variantes.py  (D10, barrido de diseno)
Las seis familias del encargo son categorias de libro. El punto de diseno real
esta dentro de una de ellas. Este script barre el espacio util:

  - Molniya 12 h con perigeo de 600 a 12.000 km (sube el cruce ecuatorial
    fuera del cinturon de protones a costa de bajar el apogeo)
  - Tundra 24 h con e de 0,15 a 0,35
  - TAP 16 h con perigeo de 8.100 (ASBM) a 14.000 km

Para cada variante: N minimo para 24/7 con el>60 sobre el Golfo de Finlandia,
distancia p90 del satelite servidor, apertura MWIR necesaria para GSD_eff
500 m, L en el cruce del ecuador magnetico, horas/dia en el cinturon de
protones, dV desde GTO Kourou y latitud de cruce del anillo GEO.

Salida: resultados/08_variantes.md
"""
import math
from orbital import (MU, RE, RAD, DEG, OMEGA_E, T_SID, Orbit, sma_from_period,
                     elev_range, site_vec, lshell, md_table)
import orbitas_def as od

STEP = 60.0
CYCLES = 4
LAT, LON, _ = od.SITES["GoF"]
SV = site_vec(LAT, LON)
R_GEO = sma_from_period(T_SID)
G0 = 9.80665
LAM_MWIR = 4.0e-6
GSD_OBJ = 500.0


def phased_rep(orb, n, t_rep):
    out = []
    for k in range(n):
        dt = k * t_rep / n
        out.append(orb.copy_with(
            M0_deg=(orb.M0 * RAD + orb.dM * dt * RAD) % 360.0,
            raan_deg=(orb.raan0 * RAD - OMEGA_E * dt * RAD) % 360.0))
    return out


def min_N(orb, nrev, th=60.0, nmax=8):
    t_rep = nrev * orb.T
    n = int(CYCLES * t_rep / STEP)
    for N in range(1, nmax + 1):
        sats = phased_rep(orb, N, t_rep)
        ok = True
        rhos = []
        elmin = 91.0
        for k in range(n):
            t = k * STEP
            be, br = -91.0, 0.0
            for s in sats:
                el, rho = elev_range(s.state_ecef(t), SV)
                if el > be:
                    be, br = el, rho
            if be < th:
                ok = False
                break
            rhos.append(br)
            elmin = min(elmin, be)
        if ok:
            rhos.sort()
            return N, rhos[int(0.9 * (len(rhos) - 1))], elmin
    return None, None, None


def belt(orb, days=4, step=20.0):
    n = int(days * 86400 / step)
    t_p = 0.0
    for k in range(n):
        x, y, z, r = orb.state_eci(k * step)
        if r - RE > 1000.0 and 1.2 <= lshell(x, y, z) < 2.5:
            t_p += step
    return t_p / days / 3600.0


def l_eq(orb):
    return orb.a * (1 - orb.e ** 2) / RE


def geo_ring_lat(orb):
    p = orb.a * (1 - orb.e ** 2)
    if orb.ra < R_GEO or orb.rp > R_GEO:
        return None
    cnu = (p / R_GEO - 1.0) / orb.e
    if abs(cnu) > 1:
        return None
    nu = math.acos(cnu)
    return abs(math.asin(math.sin(orb.i) * math.sin(orb.argp0 + nu)) * RAD)


def state_at(r, rp, ra):
    a = 0.5 * (rp + ra)
    p = 2.0 * rp * ra / (rp + ra)
    v = math.sqrt(max(MU * (2.0 / r - 1.0 / a), 0.0))
    vt = min(math.sqrt(MU * p) / r, v)
    return v, vt, math.sqrt(max(v * v - vt * vt, 0.0))


def burn(r, oa, ob, d):
    _, vt1, vr1 = state_at(r, *oa)
    _, vt2, vr2 = state_at(r, *ob)
    return math.sqrt((vr2 - vr1) ** 2 + vt1 ** 2 + vt2 ** 2
                     - 2 * vt1 * vt2 * math.cos(d))


def dv_from_gto(orb, hp0=250.0, ha0=35786.0, i0=6.0, nsplit=181):
    rp0, ra0 = RE + hp0, RE + ha0
    di = abs(orb.i * RAD - i0) * DEG
    gto = (rp0, ra0)
    inter = (min(rp0, orb.ra), max(rp0, orb.ra))
    final = (min(orb.rp, orb.ra), max(orb.rp, orb.ra))
    r1 = ra0 if orb.ra >= ra0 else rp0
    r2 = orb.ra
    best = 1e9
    for k in range(nsplit):
        d1 = di * k / (nsplit - 1)
        best = min(best, burn(r1, gto, inter, d1)
                   + burn(r2, inter, final, di - d1))
    return best * 1000.0


def aperture(R_km, el_deg):
    return 1.22 * LAM_MWIR * R_km * 1000.0 / (GSD_OBJ *
                                              math.sin(math.radians(el_deg)))


VARIANTS = []
a12 = sma_from_period(T_SID / 2.0)
for hp in (600, 1500, 3000, 5000, 8000, 10000, 12000):
    e = 1.0 - (RE + hp) / a12
    VARIANTS.append(("Molniya 12 h hp=%d km" % hp,
                     Orbit("M", a12, e, 63.435, 0, 270, 0), 2))
a24 = sma_from_period(T_SID)
for e in (0.15, 0.20, 0.25, 0.30, 0.35):
    VARIANTS.append(("Tundra 24 h e=%.2f" % e,
                     Orbit("T", a24, e, 63.435, 0, 270, 0), 1))
a16 = sma_from_period(2.0 * T_SID / 3.0)
for hp in (8100, 11000, 14000):
    e = 1.0 - (RE + hp) / a16
    VARIANTS.append(("TAP 16 h hp=%d km" % hp,
                     Orbit("P", a16, e, 65.0, 0, 270, 0), 3))

rows = []
for name, orb, nrev in VARIANTS:
    orb = od.tune_raan_apogee(orb)
    N, p90, elmin = min_N(orb, nrev)
    hb = belt(orb)
    gl = geo_ring_lat(orb)
    rows.append([name,
                 "%d" % round(orb.rp - RE), "%d" % round(orb.ra - RE),
                 "%.4f" % orb.e,
                 "%d" % N if N else ">8",
                 "%d" % round(p90) if p90 else "-",
                 "%.1f" % elmin if elmin else "-",
                 "%.2f" % aperture(p90, elmin) if p90 else "-",
                 "%.2f" % l_eq(orb),
                 "%.2f" % hb,
                 "%d" % round(dv_from_gto(orb)),
                 ("%.1f" % gl) if gl is not None else "no cruza"])

out = ["# 08 — Barrido de variantes dentro de cada familia  (D10)\n",
       "Generado por `08_variantes.py`. Sitio: Golfo de Finlandia 59,80 N "
       "25,50 E. `N` = satelites para elevacion >60 deg el 100% del tiempo. "
       "`D MWIR` = apertura para GSD_eff 500 m a la distancia p90. "
       "`L_eq` = L en el cruce del ecuador magnetico (dominante para el dano "
       "por desplazamiento en el FPA). `dV GTO` desde GTO Kourou i=6.\n"]
out.append(md_table(
    ["Variante", "hp [km]", "ha [km]", "e", "N (el>60)",
     "R p90 servidor [km]", "el_min [deg]", "D MWIR @500 m [m]", "L_eq",
     "h/dia en L1,2-2,5", "dV GTO [m/s]", "lat. cruce anillo GEO [deg]"], rows))

# ---------------------------------------------- barrido fino del perigeo
rows = []
for hp in range(2500, 6001, 250):
    e = 1.0 - (RE + hp) / a12
    o = od.tune_raan_apogee(Orbit("M", a12, e, 63.435, 0, 270, 0))
    r = [min_N(o, 2, th=th) for th in (50.0, 60.0, 70.0)]
    gl = geo_ring_lat(o)
    cell = []
    for N, p90, elmin in r:
        cell.append("N=%s" % (N or ">8") +
                    ("" if not N else " R=%d el=%.0f D=%.2f"
                     % (round(p90), elmin, aperture(p90, elmin))))
    rows.append([hp, "%.4f" % e, "%d" % round(o.ra - RE)] + cell +
                ["%.2f" % l_eq(o), "%.2f" % belt(o), "%d" % round(dv_from_gto(o)),
                 ("%.1f" % gl) if gl is not None else "no cruza"])
out.append("\n## Barrido fino del perigeo en la familia Molniya 12 h\n")
out.append("R en km, el en grados, D = apertura MWIR para GSD_eff 500 m en "
           "metros. El salto de N=3 a N=4 entre hp=3.750 y hp=4.000 km para "
           "el>60 es el compromiso central de esta familia.\n")
out.append(md_table(["hp [km]", "e", "ha [km]", "el>50", "el>60", "el>70",
                     "L_eq", "h/dia L1,2-2,5", "dV GTO [m/s]",
                     "lat. anillo GEO"], rows))

out.append("""
## Como se lee esta tabla

El parametro de diseno libre en la familia Molniya es el perigeo. Subirlo saca
el cruce del ecuador magnetico del cinturon de protones (L_eq pasa de 1,90 a
>3) y baja el apogeo, lo que mejora la distancia de diseno; el precio es que
el perigeo alto encarece el dV desde GTO y acorta la permanencia util.

Si existe una variante con L_eq > 3,0, h/dia en L1,2-2,5 = 0, N = 3 y
R p90 < 42.000 km, esa variante domina simultaneamente a Molniya clasica y a
Tundra, y no esta en la lista de seis orbitas del encargo. Es un punto de
diseno, no una familia de libro.
""")

txt = "\n".join(out) + "\n"
open("resultados/08_variantes.md", "w").write(txt)
print(txt)
