"""
05_enlace.py  (D10.5)
Presupuesto de enlace de bajada de primer orden y tasa de datos sostenible.

Modelo (todo [CALCULADO] salvo los parametros de equipo, marcados [SUPUESTO]):
  FSPL   = 20 log10(4 pi R / lambda)
  G      = 10 log10(eta (pi D / lambda)^2)
  C/N0   = EIRP - FSPL + G/T + 228,6 - L_atm - L_apunt
  Rb_max = C/N0 - (Eb/N0)_req - margen        [dBHz -> bit/s]
  Rb_eff = min(Rb_max, ancho de banda asignado * eficiencia espectral)

Tambien: tiempo de contacto diario con una estacion en Sodankyla (67,37 N,
26,63 E) con el>5 deg, y volumen diario descargable.

Salida: resultados/05_enlace.md
"""
import json, math
from orbital import elev_range, site_vec, md_table
import orbitas_def as od

C = 2.99792458e8
K_DBW = -228.6          # 10log10(k) [dBW/K/Hz]

# ---- configuraciones de equipo [SUPUESTO: valores tipicos, no ofertas]
CASES = {
    "X-band 8,2 GHz · 20 W · ant. 0,5 m · GS 7,3 m": dict(
        f=8.2e9, Ptx_W=20.0, Dsat=0.50, eta=0.60,
        Dgs=7.3, Tsys=120.0, bw_hz=375e6, bps_hz=1.0),
    "X-band 8,2 GHz · 5 W · ant. 0,3 m · GS 3,7 m": dict(
        f=8.2e9, Ptx_W=5.0, Dsat=0.30, eta=0.60,
        Dgs=3.7, Tsys=150.0, bw_hz=375e6, bps_hz=1.0),
    "Ka 26 GHz · 20 W · ant. 0,5 m · GS 7,3 m": dict(
        f=26.0e9, Ptx_W=20.0, Dsat=0.50, eta=0.60,
        Dgs=7.3, Tsys=200.0, bw_hz=1500e6, bps_hz=1.0),
}
L_ATM = 1.0        # dB (X-band, el>60 deg, cielo claro) [SUPUESTO]
L_PNT = 0.5        # dB [SUPUESTO]
EBN0_REQ = 2.5     # dB, DVB-S2 QPSK 1/2 LDPC con perdida de implementacion [SUPUESTO]
MARGIN = 3.0       # dB, requisito interno

GS = (67.37, 26.63, "Sodankyla (estacion polar; KSAT/FMI operan alli) [VERIFICAR]")

OP = json.load(open("resultados/puntos_operacion.json"))
ORDER = ["LEO-SSO-600", "LEO-ALTA-2000", "MEO-8000", "MEO-20000",
         "GEO-25E", "MOLNIYA", "TUNDRA", "TAP-ASBM"]
orbs = od.build()


def design_range(k):
    v = OP[k]
    if "R_p90_serv" in v:
        return v["R_p90_serv"]
    if k.startswith("GEO"):
        return 39344.0
    return v["R_mean40"]


def gain(D, f, eta):
    lam = C / f
    return 10 * math.log10(eta * (math.pi * D / lam) ** 2)


def fspl(R_km, f):
    lam = C / f
    return 20 * math.log10(4 * math.pi * R_km * 1000.0 / lam)


def contact_fraction(orb, lat, lon, days, step=60.0, elmin=5.0):
    sv = site_vec(lat, lon)
    n = int(days * 86400 / step)
    c = 0
    for k in range(n):
        if elev_range(orb.state_ecef(k * step), sv)[0] >= elmin:
            c += 1
    return c / n


out = ["# 05 — Presupuesto de enlace de bajada  (D10.5)\n",
       "Generado por `05_enlace.py`. Distancia de diseno = la misma que en "
       "`03_gsd.py` (p90 del satelite servidor para HEO, media de acceso para "
       "LEO/MEO). Eb/N0 requerido %.1f dB + margen %.1f dB.\n"
       % (EBN0_REQ, MARGIN)]

# ---- contacto con Sodankyla
rows = []
for k in ORDER:
    o = orbs[k]
    days = 14 if k.startswith(("LEO", "MEO")) else 8
    f = contact_fraction(o, GS[0], GS[1], days)
    rows.append([OP[k]["label"], "%.1f" % (100 * f), "%.1f" % (24 * f)])
out.append("\n## Contacto con una unica estacion en %s\n" % GS[2])
out.append("Un satelite, elevacion minima 5 deg.\n")
out.append(md_table(["Orbita", "% de tiempo en visibilidad", "h/dia"], rows))

# ---- presupuesto por configuracion
for cname, c in CASES.items():
    lam = C / c["f"]
    eirp = 10 * math.log10(c["Ptx_W"]) + gain(c["Dsat"], c["f"], c["eta"])
    gt = gain(c["Dgs"], c["f"], c["eta"]) - 10 * math.log10(c["Tsys"])
    hpbw = 70.0 * lam / c["Dsat"]
    rows = []
    for k in ORDER:
        R = design_range(k)
        L = fspl(R, c["f"])
        cn0 = eirp - L + gt + 228.6 - L_ATM - L_PNT
        rb_dB = cn0 - EBN0_REQ - MARGIN
        rb = 10 ** (rb_dB / 10.0)
        rb_bw = c["bw_hz"] * c["bps_hz"]
        rb_eff = min(rb, rb_bw)
        lim = "potencia" if rb < rb_bw else "ancho de banda"
        rows.append([OP[k]["label"], "%d" % round(R), "%.1f" % L,
                     "%.1f" % cn0,
                     "%.0f" % (rb / 1e6), "%.0f" % (rb_eff / 1e6), lim])
    out.append("\n## %s\n" % cname)
    out.append("EIRP = %.1f dBW · G/T estacion = %.1f dB/K · ancho de haz del "
               "satelite = %.2f deg · banda asignada %.0f MHz a %.1f bit/s/Hz.\n"
               % (eirp, gt, hpbw, c["bw_hz"] / 1e6, c["bps_hz"]))
    out.append(md_table(["Orbita", "R [km]", "FSPL [dB]", "C/N0 [dBHz]",
                         "Rb limitada por potencia [Mbit/s]",
                         "Rb efectiva [Mbit/s]", "limitante"], rows))

# ---- demanda de datos
out.append("""
## Demanda de datos frente a capacidad [CALCULADO]

Flujo bruto del instrumento, sin compresion:

| Sensor | Formato | Prof. | Cadencia | Tasa bruta |
|---|---|---|---|---|
| MWIR | 1280 x 1024 | 14 bit | 10 s | 1,8 Mbit/s |
| MWIR | 1280 x 1024 | 14 bit | 1 s | 18,4 Mbit/s |
| VIS pancromatico | 4096 x 4096 | 12 bit | 10 s | 20,1 Mbit/s |
| VIS pancromatico | 4096 x 4096 | 12 bit | 1 s | 201 Mbit/s |

Conclusion incomoda: **el enlace no es el cuello de botella en ninguna de las
orbitas altas.** Con 20 W y una antena de 0,5 m, el margen de potencia desde
46.000 km supera en dos ordenes de magnitud la tasa bruta de un FPA MWIR a
10 s. La frase "procesado a bordo es obligatorio" de
`investigacion_preliminar/02_fisica_y_resolucion.md` **no se sostiene con este
calculo**: el procesado a bordo se justifica por latencia, por coordinacion de
espectro y por coste de estacion, no por fisica del enlace. Hay que corregirlo.

Donde SI es cuello de botella: LEO. No por la tasa instantanea (la distancia es
minima y el C/N0 enorme) sino por el **tiempo de contacto**: ver la tabla de
visibilidad desde Sodankyla. Un LEO SSO ve una estacion polar una fraccion
pequena del dia, y la latencia media de entrega queda dominada por la espera al
siguiente pase, no por el enlace. Las orbitas altas entregan en segundos porque
el satelite que observa es el mismo que esta en visibilidad permanente.
""")

txt = "\n".join(out) + "\n"
open("resultados/05_enlace.md", "w").write(txt)
print(txt)
