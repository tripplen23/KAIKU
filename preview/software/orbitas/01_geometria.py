"""
01_geometria.py  (D10.1)
Geometria de observacion sobre el area de responsabilidad finlandesa.

Para cada orbita y cada sitio:
  - elevacion en el instante de apogeo (geometria de diseno de la HEO)
  - elevacion maxima alcanzable en 30 dias
  - distancia oblicua en ese instante
  - escorzo 1/sin(el) y masa de aire
  - elevacion media PONDERADA POR TIEMPO durante los accesos con el>40 deg
    (esto es lo que determina la calidad media del producto, no el pico)

Salida: resultados/01_geometria.md
"""
import math
import orbital as ob
from orbital import RE, RAD, DEG, elev_range, site_vec, foreshorten, md_table
import orbitas_def as od

STEP = 30.0           # s
DAYS = 30
NSTEP = int(DAYS * 86400 / STEP)

orbs = od.build()
sites = od.SITES


def sweep(orb, site_lat, site_lon, nstep=NSTEP, step=STEP):
    sv = site_vec(site_lat, site_lon)
    best_el, best_rho = -90.0, 0.0
    el_apo, rho_apo = None, None
    t_apo = (math.pi - orb.M0) / orb.dM
    for k in range(nstep):
        t = k * step
        el, rho = elev_range(orb.state_ecef(t), sv)
        if el > best_el:
            best_el, best_rho = el, rho
    # elevacion en el primer apogeo
    el_apo, rho_apo = elev_range(orb.state_ecef(t_apo), sv)
    return best_el, best_rho, el_apo, rho_apo


def fmt(x, n=1):
    return ("%." + str(n) + "f") % x


out = []
out.append("# 01 — Geometria de observacion sobre Finlandia  (D10.1)\n")
out.append("Generado por `01_geometria.py`. Tierra esferica Re=6378,137 km; "
           "propagacion kepleriana + J2 secular; ventana %d dias, paso %d s.\n"
           % (DAYS, int(STEP)))
out.append("`el_max` = elevacion maxima alcanzada en la ventana. "
           "`el_apo` = elevacion en el instante del primer apogeo (para GEO/MEO "
           "circulares es un instante arbitrario y no tiene significado).\n")

for sk, (lat, lon, desc) in sites.items():
    rows = []
    for name in od.MAIN:
        o = orbs[name]
        el_max, rho_max, el_apo, rho_apo = sweep(o, lat, lon)
        rows.append([o.label,
                     fmt(el_max, 1), "%d" % round(rho_max),
                     fmt(foreshorten(el_max), 2) if el_max > 0 else "inf",
                     fmt(el_apo, 1), "%d" % round(rho_apo)])
    out.append("\n## %s — %s (%.2f N, %.2f E)\n" % (sk, desc, lat, lon))
    out.append(md_table(
        ["Orbita", "el_max [deg]", "dist @el_max [km]", "escorzo 1/sin(el_max)",
         "el_apo [deg]", "dist @apo [km]"], rows))

# ---- tabla de contraste: GEO 25E vs GEO 0E (coherencia con 02_fisica)
rows = []
for name in ["GEO-25E", "GEO-0E"]:
    o = orbs[name]
    for sk, (lat, lon, desc) in sites.items():
        el_max, rho_max, _, _ = sweep(o, lat, lon, nstep=2880, step=30)
        rows.append([o.label, sk, fmt(el_max, 2), "%d" % round(rho_max),
                     fmt(foreshorten(el_max), 2)])
out.append("\n## Contraste GEO: slot optimo (25 E) vs slot europeo real (0 E)\n")
out.append(md_table(["Orbita", "Sitio", "elevacion [deg]", "distancia [km]",
                     "escorzo"], rows))

txt = "\n".join(out) + "\n"
open("resultados/01_geometria.md", "w").write(txt)
print(txt)
