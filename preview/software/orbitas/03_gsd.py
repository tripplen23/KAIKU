"""
03_gsd.py  (D10.3)
GSD limitada por difraccion en MWIR (3-5 um) y VIS, para D = 0,2 / 0,3 / 0,5 / 1,0 m.

Criterio: Rayleigh, theta = 1,22 lambda / D  [rad].
  GSD_nadir = theta * R                       (direccion transversal)
  GSD_eff   = theta * R / sin(el)             (direccion de maximo escorzo)
El GSD_eff es el numero que hay que usar: es el eje en el que se mide una
estela, una separacion entre buques o el movimiento de un blanco.

Punto de operacion por orbita (de 02_cobertura, resultados/puntos_operacion.json):
  - HEO/GEO: distancia p90 del satelite SERVIDOR en la constelacion 24/7 (el>60)
    y elevacion minima garantizada. Es el peor caso operativo, no el apogeo.
  - LEO/MEO: distancia media durante accesos con el>40 y elevacion media.

Tambien: apertura requerida para GSD objetivo, distancia focal y F/# con
pasos de pixel reales, y longitud de tubo estimada (entra en D11).

Salida: resultados/03_gsd.md
"""
import json, math
from orbital import md_table

LAM = {"VIS 0,55 um": 0.55e-6, "NIR 0,9 um": 0.9e-6,
       "MWIR 4,0 um": 4.0e-6, "LWIR 10 um": 10.0e-6}
APER = [0.2, 0.3, 0.5, 1.0]
PITCH = {"VIS 0,55 um": 5.5e-6, "NIR 0,9 um": 5.5e-6,
         "MWIR 4,0 um": 15.0e-6, "LWIR 10 um": 15.0e-6}   # [SUPUESTO] pasos comerciales

OP = json.load(open("resultados/puntos_operacion.json"))

# punto de operacion (R [km], elevacion [deg], comentario)
DESIGN = {}
for k, v in OP.items():
    if "R_p90_serv" in v:
        DESIGN[k] = (v["R_p90_serv"], v["el_min"],
                     "p90 del servidor, constelacion N=%d (el>60)" % v["N60"])
    elif k.startswith("GEO"):
        DESIGN[k] = (39344.0, 22.14, "estatico sobre el Golfo (slot 25 E)")
    else:
        DESIGN[k] = (v["R_mean40"], v["el_mean"], "media durante accesos el>40")

ORDER = ["LEO-SSO-600", "LEO-ALTA-2000", "MEO-8000", "MEO-20000",
         "GEO-25E", "MOLNIYA", "TUNDRA", "TAP-ASBM"]


def theta(lam, D):
    return 1.22 * lam / D


def gsd(lam, D, R_km, el_deg):
    t = theta(lam, D)
    nad = t * R_km * 1000.0
    return nad, nad / math.sin(math.radians(el_deg))


out = ["# 03 — GSD limitada por difraccion  (D10.3)\n",
       "Generado por `03_gsd.py`. theta = 1,22 lambda/D. "
       "GSD_eff = theta*R/sin(el). Sin considerar MTF del detector, jitter, "
       "ni atmosfera: es el techo fisico, no el rendimiento alcanzable. "
       "Un sistema real entrega entre 1,3x y 2x peor. [SUPUESTO ACOTADO]\n"]

rows = [[OP[k]["label"], "%d" % round(DESIGN[k][0]), "%.1f" % DESIGN[k][1],
         "%.2f" % (1.0 / math.sin(math.radians(DESIGN[k][1]))), DESIGN[k][2]]
        for k in ORDER]
out.append("\n## Puntos de operacion usados\n")
out.append(md_table(["Orbita", "R diseno [km]", "elevacion [deg]",
                     "escorzo 1/sin(el)", "criterio"], rows))

for band in ("MWIR 4,0 um", "VIS 0,55 um"):
    lam = LAM[band]
    out.append("\n## GSD efectiva [m] — %s (direccion de maximo escorzo)\n" % band)
    rows = []
    for k in ORDER:
        R, el, _ = DESIGN[k]
        r = [OP[k]["label"]]
        for D in APER:
            _, eff = gsd(lam, D, R, el)
            r.append("%s" % (("%.1f" % eff) if eff < 100 else "%d" % round(eff)))
        rows.append(r)
    out.append(md_table(["Orbita"] + ["D=%.1f m" % D for D in APER], rows))

# ---- apertura requerida para GSD objetivo
TARGETS = [("MWIR 4,0 um", 500.0), ("MWIR 4,0 um", 300.0),
           ("MWIR 4,0 um", 100.0), ("VIS 0,55 um", 50.0),
           ("VIS 0,55 um", 20.0)]
out.append("\n## Apertura requerida [m] para una GSD efectiva objetivo\n")
rows = []
for k in ORDER:
    R, el, _ = DESIGN[k]
    r = [OP[k]["label"]]
    for band, g in TARGETS:
        D = 1.22 * LAM[band] * R * 1000.0 / (g * math.sin(math.radians(el)))
        r.append("%.2f" % D)
    rows.append(r)
out.append(md_table(["Orbita"] + ["%s @%d m" % (b.split()[0], int(g))
                                  for b, g in TARGETS], rows))
out.append("\n**Linea roja de cumplimiento: 0,50 m.** USML XV(e)(2) situa el "
           "umbral de control en 0,50 m de apertura (fuente: Compliance & "
           "Legal, `canal/iteracion_01/06_compliance_legal.md`). Toda celda "
           "por encima de 0,50 m saca la carga de la regla D12 de cadena de "
           "suministro europea. Las aperturas del encargo (0,2 / 0,3 / 0,5 m) "
           "estan dentro; 1,0 m no.\n")

# ---- GSD alcanzable con la apertura maxima legal
out.append("\n## GSD efectiva alcanzable con D = 0,50 m exactos "
           "(apertura maxima sin control USML XV(e)(2))\n")
rows = []
for k in ORDER:
    R, el, _ = DESIGN[k]
    r = [OP[k]["label"], "%d" % round(R), "%.1f" % el]
    for band in ("MWIR 4,0 um", "VIS 0,55 um"):
        _, eff = gsd(LAM[band], 0.50, R, el)
        r.append("%d" % round(eff))
    rows.append(r)
out.append(md_table(["Orbita", "R diseno [km]", "el [deg]",
                     "GSD_eff MWIR [m]", "GSD_eff VIS [m]"], rows))

# ---- focal, F/# y longitud de tubo
out.append("\n## Distancia focal, F/# y longitud de tubo (Nyquist: 1 px = GSD)\n")
out.append("Paso de pixel supuesto: MWIR 15 um, VIS 5,5 um [SUPUESTO, pasos "
           "comerciales]. f = pitch * R / GSD_nadir. Longitud de tubo estimada "
           "como 0,30*f para un Cassegrain plegado (factor tipico 0,25-0,35) "
           "[SUPUESTO].\n")
rows = []
for k in ORDER:
    R, el, _ = DESIGN[k]
    for band, g in (("MWIR 4,0 um", 500.0), ("VIS 0,55 um", 50.0)):
        D = 1.22 * LAM[band] * R * 1000.0 / (g * math.sin(math.radians(el)))
        gsd_nadir = g * math.sin(math.radians(el))
        f = PITCH[band] * R * 1000.0 / gsd_nadir
        rows.append([OP[k]["label"], band, "%d" % int(g), "%.2f" % D,
                     "%.2f" % f, "%.1f" % (f / D), "%.2f" % (0.30 * f)])
out.append(md_table(["Orbita", "Banda", "GSD_eff obj [m]", "D [m]", "f [m]",
                     "F/#", "tubo ~0,3f [m]"], rows))

txt = "\n".join(out) + "\n"
open("resultados/03_gsd.md", "w").write(txt)
print(txt)
