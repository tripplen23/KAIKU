"""
10_alto_norte.py  (D10, revision del area de responsabilidad)
Product & Market documenta que la custodia continua del Golfo de Finlandia ya
la presta GOFREP desde tierra (radar + AIS, 24 h, IMO MSC.139(76)). El hueco
para orbita alta esta en el Alto Norte y el Barents. Eso mueve el area de
responsabilidad de 59-61 N a 68-78 N y **cambia el optimo orbital**, porque el
apogeo de una HEO con argp=270 cae en la latitud igual a la inclinacion.

Este script recalcula:
  (a) cobertura de las ocho orbitas principales contra el nuevo AoR
  (b) barrido de inclinacion 63,4 a 80 deg para la familia 12 h, con la
      penalizacion que supone abandonar la inclinacion critica (deriva del
      argumento del perigeo y dV anual para corregirla)
  (c) el AoR es multi-punto: se exige cobertura simultanea de TODOS los sitios,
      no de uno. Ese es el requisito real de un teatro.

Salida: resultados/10_alto_norte.md
"""
import math
from orbital import (MU, RE, RAD, DEG, OMEGA_E, T_SID, Orbit, sma_from_period,
                     elev_range, site_vec, md_table)
import orbitas_def as od

STEP = 60.0
CYCLES = 3
LAM_MWIR = 4.0e-6
GSD_OBJ = 500.0

REPEAT = {"GEO-25E": 1, "MOLNIYA": 2, "TUNDRA": 1, "TAP-ASBM": 3}
AOR = [(v[0], v[1]) for k, v in od.SITES_NORTE.items() if k != "GoF"]
AOR_ALL = [(v[0], v[1]) for v in od.SITES_NORTE.values()]
SV_AOR = [site_vec(a, b) for a, b in AOR]
SV_ALL = [site_vec(a, b) for a, b in AOR_ALL]


def phased(orb, n, t_rep):
    return [orb.copy_with(
        M0_deg=(orb.M0 * RAD + orb.dM * (k * t_rep / n) * RAD) % 360.0,
        raan_deg=(orb.raan0 * RAD - OMEGA_E * (k * t_rep / n) * RAD) % 360.0)
        for k in range(n)]


def min_N_multi(orb, nrev, svs, th, nmax=8, step=STEP):
    """N minimo para que TODOS los sitios tengan siempre un satelite con el>=th."""
    t_rep = nrev * orb.T
    n = int(CYCLES * t_rep / step)
    for N in range(1, nmax + 1):
        sats = phased(orb, N, t_rep)
        ok = True
        elmin, rhos = 91.0, []
        for k in range(n):
            t = k * step
            states = [s.state_ecef(t) for s in sats]
            for sv in svs:
                be, br = -91.0, 0.0
                for st in states:
                    el, rho = elev_range(st, sv)
                    if el > be:
                        be, br = el, rho
                if be < th:
                    ok = False
                    break
                if be < elmin:
                    elmin = be
                rhos.append(br)
            if not ok:
                break
        if ok:
            rhos.sort()
            return N, rhos[int(0.9 * (len(rhos) - 1))], elmin
    return None, None, None


def frac_multi(orb, svs, days, th, step=STEP):
    """Fraccion de tiempo en que UN satelite ve todos los sitios con el>=th."""
    n = int(days * 86400 / step)
    c = 0
    for k in range(n):
        st = orb.state_ecef(k * step)
        if all(elev_range(st, sv)[0] >= th for sv in svs):
            c += 1
    return c / n


def ap(R, el):
    return 1.22 * LAM_MWIR * R * 1000.0 / (GSD_OBJ * math.sin(math.radians(el)))


def gsd_at_D(R, el, D=0.50):
    """GSD_eff [m] con la apertura maxima no controlada por USML XV(e)(2)."""
    return 1.22 * LAM_MWIR * R * 1000.0 / (D * math.sin(math.radians(el)))


orbs = od.build()
out = ["# 10 — Cobertura contra el area de responsabilidad del Alto Norte\n",
       "AoR: Barents central 73 N 30 E · Kola/Varanger 70 N 35 E · "
       "Mar de Noruega 68 N 10 E · Svalbard sur 76 N 18 E · Fram 78 N 5 E. "
       "El Golfo de Finlandia se mantiene solo como referencia heredada "
       "(GOFREP ya lo cubre desde tierra).\n",
       "Criterio exigente: **todos** los sitios del AoR vistos simultaneamente "
       "por al menos un satelite. Paso %d s, %d ciclos de repeticion.\n"
       % (int(STEP), CYCLES)]

# ---- (a) las ocho orbitas principales
rows = []
for k in od.MAIN:
    o = orbs[k]
    f40 = frac_multi(o, SV_AOR, 8 if k in REPEAT else 14, 40.0)
    f20 = frac_multi(o, SV_AOR, 8 if k in REPEAT else 14, 20.0)
    if k in REPEAT:
        N40, p90, elmin = min_N_multi(o, REPEAT[k], SV_AOR, 40.0)
        N50 = min_N_multi(o, REPEAT[k], SV_AOR, 50.0)[0]
        cell = ["%s" % (N40 or ">8"), "%s" % (N50 or ">8"),
                "%d" % round(p90) if p90 else "-",
                "%.1f" % elmin if elmin else "-",
                ("%.2f%s" % (ap(p90, elmin),
                             "" if ap(p90, elmin) <= 0.50 else " **>USML**"))
                if p90 else "-",
                "%d" % round(gsd_at_D(p90, elmin)) if p90 else "-"]
    else:
        cell = ["n/a", "n/a", "-", "-", "-", "-"]
    rows.append([o.label, "%.1f" % (100 * f20), "%.1f" % (100 * f40)] + cell)
out.append("\n## Las ocho orbitas frente al AoR del Alto Norte\n")
out.append(md_table(["Orbita", "%t 1 sat ve TODO el AoR a el>20",
                     "idem a el>40", "N para el>40 en todo el AoR",
                     "N para el>50", "R p90 [km]", "el_min [deg]",
                     "D MWIR @500 m [m]",
                     "GSD_eff MWIR con D=0,50 m [m]"], rows))

# ---- (b) barrido de inclinacion, familia 12 h hp=5.000 km
a12 = sma_from_period(T_SID / 2.0)
hp = 5000.0
e12 = 1.0 - (RE + hp) / a12
rows = []
for inc in (63.435, 66.0, 68.0, 70.0, 72.0, 75.0, 80.0):
    o = od.tune_raan_apogee(Orbit("M", a12, e12, inc, 0, 270, 0))
    N40, p90, elmin = min_N_multi(o, 2, SV_AOR, 40.0)
    N50 = min_N_multi(o, 2, SV_AOR, 50.0)[0]
    Nall = min_N_multi(o, 2, SV_ALL, 40.0)[0]
    dargp_yr = o.dargp * RAD * 86400 * 365.25
    rows.append(["%.3f" % inc, "%s" % (N40 or ">8"), "%s" % (N50 or ">8"),
                 "%s" % (Nall or ">8"),
                 "%d" % round(p90) if p90 else "-",
                 "%.1f" % elmin if elmin else "-",
                 "%.2f" % ap(p90, elmin) if p90 else "-",
                 "%d" % round(gsd_at_D(p90, elmin)) if p90 else "-",
                 "%+.2f" % dargp_yr])
out.append("\n## Barrido de inclinacion, familia 12 h con hp=5.000 km "
           "(a=%.0f km, e=%.4f, ha=%.0f km)\n"
           % (a12, e12, a12 * (1 + e12) - RE))
out.append("`N AoR+GoF` exige ver ademas el Golfo de Finlandia. La ultima "
           "columna es la deriva secular J2 del argumento del perigeo: a "
           "i=63,435 es nula por construccion; fuera de ahi hay que "
           "mantenerla o aceptar que el apogeo migra en latitud. [CALCULADO]\n")
out.append(md_table(["i [deg]", "N (el>40, AoR)", "N (el>50, AoR)",
                     "N (el>40, AoR+GoF)", "R p90 [km]", "el_min [deg]",
                     "D MWIR @500 m [m]", "GSD_eff con D=0,50 m [m]",
                     "deriva argp [deg/ano]"], rows))

# ---- (c) barrido de perigeo a la mejor inclinacion encontrada
rows = []
for hp2 in (600, 2500, 5000, 8000, 11000):
    e2 = 1.0 - (RE + hp2) / a12
    for inc in (63.435, 70.0):
        o = od.tune_raan_apogee(Orbit("M", a12, e2, inc, 0, 270, 0))
        N40, p90, elmin = min_N_multi(o, 2, SV_AOR, 40.0)
        rows.append(["%d" % hp2, "%.3f" % inc, "%d" % round(a12 * (1 + e2) - RE),
                     "%s" % (N40 or ">8"),
                     "%d" % round(p90) if p90 else "-",
                     "%.1f" % elmin if elmin else "-",
                     "%.2f" % ap(p90, elmin) if p90 else "-",
                     "%d" % round(gsd_at_D(p90, elmin)) if p90 else "-",
                     "%.2f" % (a12 * (1 - e2 ** 2) / RE)])
out.append("\n## Perigeo x inclinacion, familia 12 h, frente al AoR del Alto "
           "Norte (el>40 en todos los sitios)\n")
out.append(md_table(["hp [km]", "i [deg]", "ha [km]", "N", "R p90 [km]",
                     "el_min [deg]", "D MWIR @500 m [m]",
                     "GSD_eff con D=0,50 m [m]", "L en cruce ecuatorial"], rows))

txt = "\n".join(out) + "\n"
open("resultados/10_alto_norte.md", "w").write(txt)
print(txt)
