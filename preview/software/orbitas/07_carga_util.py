"""
07_carga_util.py  (D11)
Masa, potencia y volumen de la carga util en cada orbita, y veredicto
"cabe como carga hospedada" / "exige satelite propio".

TODO EL MODELO DE MASA ES PARAMETRICO Y ES UN [SUPUESTO]. No hay en el
repositorio una masa publicada de un OTA de 0,3-0,5 m de clase espacial con la
que anclarlo. El modelo se declara entero para que cualquiera pueda sustituir
los coeficientes:

  M_OTA  = C_ota * D^2,5      C_ota en [120, 300] kg/m^2,5   [SUPUESTO]
  M_FPA  = 3 kg (IDDCA: detector + dewar + electronica de proximidad) [SUPUESTO]
  M_cryo = 5 kg, 80 W  (pulse tube clase microsatelite, ~1 W a 80-110 K)
           Cota superior real conocida: el LPTC europeo (Air Liquide/Thales
           Cryogenics/CEA-SBT, vuela en MTG y MetOp-SG) da 2,3 W a 50 K con
           <=160 W electricos y 15 anos de vida. [VERIFICADO, ver fuentes]
  M_elec = 8 kg, 35 W   (procesado + control)  [SUPUESTO]
  M_struct = 30% de la suma anterior            [SUPUESTO]

Volumen: longitud de tubo = 0,30 * f (Cassegrain plegado) + parasol de 2,5 D
(mision que mira a la Tierra con el Sol cerca del campo en verano artico).
Diametro de envolvente = D + 0,15 m.

Salida: resultados/07_carga_util.md
"""
import json, math
from orbital import md_table

LAM_MWIR, LAM_VIS = 4.0e-6, 0.55e-6
PITCH_MWIR, PITCH_VIS = 15.0e-6, 5.5e-6
C_OTA_LO, C_OTA_HI = 120.0, 300.0
M_FPA, M_CRYO, M_ELEC = 3.0, 5.0, 8.0
P_CRYO, P_ELEC, P_TX = 80.0, 35.0, 60.0
F_STRUCT = 0.30

REQ = {
    "REQ-A  MWIR GSD_eff <= 500 m": (LAM_MWIR, 500.0, PITCH_MWIR),
    "REQ-B  VIS GSD_eff <= 50 m":   (LAM_VIS, 50.0, PITCH_VIS),
    "REQ-C  MWIR <= 300 m":         (LAM_MWIR, 300.0, PITCH_MWIR),
}

OP = json.load(open("resultados/puntos_operacion.json"))
ORDER = ["LEO-SSO-600", "LEO-ALTA-2000", "MEO-8000", "MEO-20000",
         "GEO-25E", "MOLNIYA", "TUNDRA", "TAP-ASBM"]


def design(k):
    v = OP[k]
    if "R_p90_serv" in v:
        return v["R_p90_serv"], v["el_min"]
    if k.startswith("GEO"):
        return 39344.0, 22.14
    return v["R_mean40"], v["el_mean"]


def sizing(lam, gsd_eff, pitch, R_km, el_deg):
    s = math.sin(math.radians(el_deg))
    D = 1.22 * lam * R_km * 1000.0 / (gsd_eff * s)
    gsd_nadir = gsd_eff * s
    f = pitch * R_km * 1000.0 / gsd_nadir
    m_ota_lo = C_OTA_LO * D ** 2.5
    m_ota_hi = C_OTA_HI * D ** 2.5
    def tot(m_ota):
        base = m_ota + M_FPA + M_CRYO + M_ELEC
        return base * (1 + F_STRUCT)
    L = 0.30 * f + 2.5 * D
    return dict(D=D, f=f, fnum=f / D, m_lo=tot(m_ota_lo), m_hi=tot(m_ota_hi),
                P=P_CRYO + P_ELEC + P_TX, L=L, dia=D + 0.15,
                vol=math.pi * ((D + 0.15) / 2) ** 2 * L)


def verdict(m_hi, P, L):
    if m_hi < 50 and P < 200 and L < 1.0:
        return "carga hospedada en casi cualquier bus"
    if m_hi < 150 and P < 300 and L < 2.0:
        return "carga hospedada negociable en bus GEO/HEO grande"
    return "**exige satelite propio**"


out = ["# 07 — Dimensionado de la carga util por orbita  (D11)\n",
       "Generado por `07_carga_util.py`. Modelo de masa parametrico; "
       "coeficientes declarados en la cabecera del script. Rango de masa = "
       "coeficiente de OTA entre 120 y 300 kg/m^2,5. Potencia fija: "
       "%.0f W criogenerador + %.0f W electronica + %.0f W transmisor = %.0f W "
       "[SUPUESTO].\n" % (P_CRYO, P_ELEC, P_TX, P_CRYO + P_ELEC + P_TX)]

for rname, (lam, g, pitch) in REQ.items():
    rows = []
    for k in ORDER:
        R, el = design(k)
        s = sizing(lam, g, pitch, R, el)
        rows.append([OP[k]["label"], "%.2f" % s["D"], "%.2f" % s["f"],
                     "%.1f" % s["fnum"],
                     "%.0f - %.0f" % (s["m_lo"], s["m_hi"]),
                     "%.0f" % s["P"], "%.2f" % s["L"], "%.2f" % s["dia"],
                     "%.3f" % s["vol"],
                     verdict(s["m_hi"], s["P"], s["L"])])
    out.append("\n## %s\n" % rname)
    out.append(md_table(["Orbita", "D [m]", "f [m]", "F/#", "masa carga [kg]",
                         "potencia [W]", "long. tubo+parasol [m]",
                         "diametro envolv. [m]", "volumen [m3]", "veredicto"],
                        rows))

out.append("""
## Lectura

1. **El dimensionado de la carga lo fija la distancia, no la orbita.** Entre
   Molniya y Tundra hay un 16,8% de diferencia de distancia de diseno (39.638
   frente a 46.304 km, p90 del satelite servidor). Con la elevacion minima de
   cada una, la apertura necesaria sube un 17,9% y la masa de OTA, con
   exponente 2,5, un **51%** para Tundra a igual requisito. Ese es el precio
   exacto de la ventaja de radiacion de Tundra. [CALCULADO]
2. **Desde LEO, el instrumento es trivial y no hay producto.** Una apertura de
   1-4 cm cumple cualquiera de los tres requisitos. Eso confirma que en LEO la
   barrera de entrada no es optica, es constelacion: 576 satelites para
   persistencia (ver `02_cobertura.md`). No es nuestro juego.
3. **El criogenerador y su potencia, no la optica, son lo que te echa de una
   carga hospedada pequena.** 175 W continuos es mucho para un hueco de
   oportunidad. Un bus de telecomunicaciones de clase GEO/HEO (varios kW) lo
   absorbe sin problema; un microsatelite de 100 kg, no.
4. **El parasol, no el tubo, domina la envolvente** en las aperturas pequenas.
   Un instrumento que mira a la Tierra desde el apogeo con el Sol cerca del
   campo necesita rechazo de luz parasita; es el componente que mas crece si se
   quiere operar tambien en verano artico con el Sol a 24 h.
""")

txt = "\n".join(out) + "\n"
open("resultados/07_carga_util.md", "w").write(txt)
print(txt)
