"""
09_punto_diseno.py
Ficha completa del punto de diseno recomendado y de sus dos alternativas,
para que la recomendacion sea tan reproducible como el descarte.

  BASELINE : HEO 12 h con perigeo elevado — 4.500 x 35.867 km, i=63,435,
             argp=270. N=3 satelites espaciados 7,98 h sobre la misma traza.
             Apertura 0,50 m (techo USML XV(e)(2)).
  CRECIM.  : el mismo con hp=5.000 km y N=4 (mejor GSD y cero cinturon).
  ALT-1    : Molniya clasica 600 x 39.767 km (menor dV, mejor distancia,
             pero cruza el cinturon de protones)
  ALT-2    : Tundra 24 h e=0,25 (radiacion minima, pero +51% masa de OTA,
             +80% dV y cruce de la region protegida GEO)

Salida: resultados/09_punto_diseno.md
"""
import math
from orbital import (MU, RE, RAD, DEG, OMEGA_E, T_SID, Orbit, sma_from_period,
                     elev_range, site_vec, lshell, md_table)
import orbitas_def as od

STEP = 30.0
LAM_MWIR, LAM_VIS = 4.0e-6, 0.55e-6
C_LO, C_HI = 120.0, 300.0
M_FIX, F_STRUCT = 16.0, 0.30      # FPA+cryo+elec; margen estructural

a12 = sma_from_period(T_SID / 2.0)
a24 = sma_from_period(T_SID)

CASES = {
    "BASELINE 12 h hp=4.500 km, N=3": (
        od.tune_raan_apogee(Orbit("B", a12, 1 - (RE + 4500.0) / a12,
                                  63.435, 0, 270, 0)), 2, 3),
    "CRECIMIENTO 12 h hp=5.000 km, N=4": (
        od.tune_raan_apogee(Orbit("C", a12, 1 - (RE + 5000.0) / a12,
                                  63.435, 0, 270, 0)), 2, 4),
    "ALT-1 Molniya clasica hp=600 km": (
        od.tune_raan_apogee(Orbit("A1", a12, 1 - (RE + 600.0) / a12,
                                  63.435, 0, 270, 0)), 2, 3),
    "ALT-2 Tundra e=0,25": (
        od.tune_raan_apogee(Orbit("A2", a24, 0.25, 63.435, 0, 270, 0)), 1, 3),
}


def phased(orb, n, t_rep):
    return [orb.copy_with(
        M0_deg=(orb.M0 * RAD + orb.dM * (k * t_rep / n) * RAD) % 360.0,
        raan_deg=(orb.raan0 * RAD - OMEGA_E * (k * t_rep / n) * RAD) % 360.0)
        for k in range(n)]


def served(sats, lat, lon, t_rep, cycles=4, step=STEP):
    sv = site_vec(lat, lon)
    n = int(cycles * t_rep / step)
    els, rhos = [], []
    for k in range(n):
        t = k * step
        be, br = -91.0, 0.0
        for s in sats:
            el, rho = elev_range(s.state_ecef(t), sv)
            if el > be:
                be, br = el, rho
        els.append(be)
        rhos.append(br)
    els_s, rhos_s = sorted(els), sorted(rhos)
    return dict(el_min=els_s[0], el_med=els_s[len(els) // 2],
                R_med=rhos_s[len(rhos) // 2],
                R_p90=rhos_s[int(0.9 * (len(rhos) - 1))], R_max=rhos_s[-1])


def ap(lam, gsd, R, el):
    return 1.22 * lam * R * 1000.0 / (gsd * math.sin(math.radians(el)))


def mass(D):
    lo = (C_LO * D ** 2.5 + M_FIX) * (1 + F_STRUCT)
    hi = (C_HI * D ** 2.5 + M_FIX) * (1 + F_STRUCT)
    return lo, hi


out = ["# 09 — Ficha del punto de diseno recomendado\n",
       "Generado por `09_punto_diseno.py`. Constelacion de 3 satelites "
       "espaciados T_rep/3 sobre la misma traza, con correccion de nodo. "
       "Estadistica del satelite servidor (el de mayor elevacion en cada "
       "instante) sobre 4 ciclos de repeticion, paso %d s.\n" % int(STEP)]

for name, (orb, nrev, N) in CASES.items():
    t_rep = nrev * orb.T
    sats = phased(orb, N, t_rep)
    rows = []
    for sk in ("Barents-C", "Kola", "Noruega", "Svalbard-S", "Fram", "GoF"):
        lat, lon, desc = od.SITES_NORTE[sk]
        s = served(sats, lat, lon, t_rep)
        rows.append([desc, "%.1f" % s["el_min"], "%.1f" % s["el_med"],
                     "%.2f" % (1 / math.sin(math.radians(s["el_min"]))),
                     "%d" % round(s["R_med"]), "%d" % round(s["R_p90"]),
                     "%d" % round(s["R_max"])])
    out.append("\n## %s\n" % name)
    out.append("a = %.0f km · e = %.4f · i = %.3f deg · argp = %.0f deg · "
               "T = %.3f h · hp = %.0f km · ha = %.0f km · "
               "N = %d satelites espaciados %.2f h · "
               "L en cruce del ecuador magnetico = %.2f\n"
               % (orb.a, orb.e, orb.i * RAD, orb.argp0 * RAD, orb.T / 3600.0,
                  orb.rp - RE, orb.ra - RE, N, t_rep / N / 3600.0,
                  orb.a * (1 - orb.e ** 2) / RE))
    out.append(md_table(["Sitio", "el min [deg]", "el mediana [deg]",
                         "escorzo peor caso", "R mediana [km]", "R p90 [km]",
                         "R max [km]"], rows))

    # peor caso sobre TODO el AoR del Alto Norte
    worst_el, worst_R = 91.0, 0.0
    for sk in ("Barents-C", "Kola", "Noruega", "Svalbard-S", "Fram"):
        lat, lon, _d = od.SITES_NORTE[sk]
        st = served(sats, lat, lon, t_rep)
        if st["el_min"] < worst_el:
            worst_el = st["el_min"]
        if st["R_p90"] > worst_R:
            worst_R = st["R_p90"]
    rows = []
    for band, lam, g in (("MWIR 4,0 um", LAM_MWIR, 500.0),
                         ("MWIR 4,0 um", LAM_MWIR, 300.0),
                         ("VIS 0,55 um", LAM_VIS, 50.0)):
        D = ap(lam, g, worst_R, worst_el)
        lo, hi = mass(D)
        rows.append([band, "%d" % int(g), "%.2f" % D,
                     "si" if D <= 0.50 else "**NO, controlado**",
                     "%.0f - %.0f" % (lo, hi)])
    for D in (0.30, 0.40, 0.50):
        for band, lam in (("MWIR 4,0 um", LAM_MWIR), ("VIS 0,55 um", LAM_VIS)):
            g = 1.22 * lam * worst_R * 1000.0 / (D * math.sin(math.radians(worst_el)))
            lo, hi = mass(D)
            rows.append([band, "-> %d (resultante)" % round(g), "%.2f" % D,
                         "si", "%.0f - %.0f" % (lo, hi)])
    out.append("\nPeor caso sobre TODO el AoR del Alto Norte: "
               "el_min = %.1f deg, R p90 = %d km.\n" % (worst_el, round(worst_R)))
    out.append(md_table(["Banda", "GSD_eff objetivo [m]", "apertura D [m]",
                         "bajo umbral USML 0,50 m",
                         "masa de carga [kg] (parametrico)"], rows))

txt = "\n".join(out) + "\n"
open("resultados/09_punto_diseno.md", "w").write(txt)
print(txt)
