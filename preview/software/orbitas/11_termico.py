"""
11_termico.py  (hipotesis IP-2 de Compliance & Legal)
Puede un radiador pasivo multietapa llevar un FPA MWIR a 110-150 K en la
ventana de apogeo, eliminando el criogenerador?

Modelo de balance estacionario, cara plana, un solo nodo:

  eps * sigma * A * T^4  =  Q_int + Q_par + Q_tierra + Q_sol

  Q_tierra = A * F_e * (OLR + alb * S * k_ilum)
  F_e      = (Re/r)^2      factor de vista placa-plana -> disco terrestre,
                           con la placa apuntando al centro de la Tierra.
                           Un radiador anti-nadir con pantalla ve una
                           fraccion f_fuga de eso. f_fuga = 1% [SUPUESTO].
  Q_sol    = 0 si el radiador nunca ve el Sol (requisito de diseno duro).

Constantes: sigma=5,670374e-8, S=1361 W/m2, OLR terrestre medio 237 W/m2,
albedo 0,30, eps=0,90.

Lo que este calculo SI decide: si el area de radiador es de centimetros o de
metros. Lo que NO decide: si los parasitos reales (soportes, mazo, MLI,
baffle) caben en el presupuesto supuesto. Eso es un modelo termico de verdad.

Salida: resultados/11_termico.md
"""
import math
from orbital import RE, RAD, Orbit, sma_from_period, T_SID, md_table
import orbitas_def as od

SIGMA = 5.670374419e-8
S_SOL = 1361.0
OLR = 237.0
ALB = 0.30
EPS = 0.90
F_FUGA = 0.01        # fraccion del factor de vista nadir que ve un radiador
                     # anti-nadir con pantalla [SUPUESTO]

orbs = od.build()
ORDER = ["LEO-SSO-600", "LEO-ALTA-2000", "MEO-8000", "MEO-20000",
         "GEO-25E", "MOLNIYA", "TUNDRA", "TAP-ASBM"]
a12 = sma_from_period(T_SID / 2.0)
EXTRA = {"BASELINE Molniya hp=5.000 km":
         od.tune_raan_apogee(Orbit("B", a12, 1 - (RE + 5000.0) / a12,
                                   63.435, 0, 270, 0))}


def fview(r):
    return (RE / r) ** 2


def flux_nadir(r, k_ilum=1.0):
    return fview(r) * (OLR + ALB * S_SOL * k_ilum)


def T_eq(q_total_wm2):
    return (q_total_wm2 / (EPS * SIGMA)) ** 0.25


def area_needed(T, Q_int_W, r):
    """Area [m2] para mantener T con carga interna Q_int y fuga terrestre."""
    q_out = EPS * SIGMA * T ** 4
    q_in_env = F_FUGA * flux_nadir(r)
    if q_out <= q_in_env:
        return float('inf')
    return Q_int_W / (q_out - q_in_env)


out = ["# 11 — Radiador pasivo criogenico: viabilidad de primer orden\n",
       "Generado por `11_termico.py`. eps=0,90, OLR=237 W/m2, albedo=0,30, "
       "S=1361 W/m2. Fuga de vista a la Tierra de un radiador anti-nadir con "
       "pantalla: %.0f%% del factor de vista nadir [SUPUESTO].\n"
       % (100 * F_FUGA)]

# ---- entorno por orbita
rows = []
allo = [(orbs[k].label, orbs[k]) for k in ORDER] + list(EXTRA.items())
for label, o in allo:
    r_apo, r_per = o.ra, o.rp
    rows.append([label,
                 "%.4f" % fview(r_apo), "%.1f" % flux_nadir(r_apo),
                 "%.0f" % T_eq(flux_nadir(r_apo)),
                 "%.4f" % fview(r_per), "%.1f" % flux_nadir(r_per),
                 "%.0f" % T_eq(flux_nadir(r_per))])
out.append("\n## Carga ambiental terrestre segun el radio orbital\n")
out.append("`F_e` = factor de vista de una placa que mira al centro de la "
           "Tierra. `T_eq nadir` = temperatura de equilibrio de esa placa sin "
           "ninguna otra carga: demuestra que un radiador criogenico **no "
           "puede mirar a la Tierra en ninguna orbita**, y por que el problema "
           "es de geometria y pantalla, no de area.\n")
out.append(md_table(["Orbita", "F_e apogeo", "flujo nadir apogeo [W/m2]",
                     "T_eq nadir apogeo [K]", "F_e perigeo",
                     "flujo nadir perigeo [W/m2]", "T_eq nadir perigeo [K]"],
                    rows))

# ---- area de radiador
out.append("\n## Area de radiador necesaria [m2], radiador anti-nadir con "
           "pantalla solar\n")
for label, o in [("BASELINE Molniya hp=5.000 km (apogeo r=%.0f km)"
                  % EXTRA["BASELINE Molniya hp=5.000 km"].ra,
                  EXTRA["BASELINE Molniya hp=5.000 km"].ra),
                 ("LEO SSO 600 km (r=%.0f km)" % orbs["LEO-SSO-600"].ra,
                  orbs["LEO-SSO-600"].ra)]:
    rows = []
    for T in (80.0, 110.0, 130.0, 150.0):
        q_out = EPS * SIGMA * T ** 4
        r = []
        for Q in (0.2, 0.5, 1.0, 2.0):
            A = area_needed(T, Q, o)
            r.append("inf" if A == float('inf') else
                     ("%.3f (%.0fx%.0f cm)" % (A, 100 * math.sqrt(A),
                                               100 * math.sqrt(A))))
        rows.append(["%.0f" % T, "%.2f" % q_out,
                     "%.3f" % (F_FUGA * flux_nadir(o))] + r)
    out.append("\n### %s\n" % label)
    out.append(md_table(["T objetivo [K]", "emision util [W/m2]",
                         "fuga terrestre [W/m2]"] +
                        ["Q_int=%.1f W" % q for q in (0.2, 0.5, 1.0, 2.0)],
                        rows))

# ---- transitorio de perigeo
out.append("\n## Transitorio de perigeo (BASELINE 12 h, hp=5.000 km)\n")
o = EXTRA["BASELINE Molniya hp=5.000 km"]
STEP = 10.0
n = int(o.T / STEP)
t_below = {}
for lim in (12000.0, 15000.0, 20000.0):
    c = 0
    for k in range(n):
        _, _, _, r = o.state_eci(k * STEP)
        if r - RE < lim:
            c += 1
    t_below[lim] = c * STEP / 3600.0
rows = []
C_TH = 800.0   # J/K, conjunto frio de ~2 kg a ~0,4 J/g/K a 110 K [SUPUESTO]
for lim, h in t_below.items():
    # exceso de flujo respecto al apogeo, sobre un radiador de 0,15 m2
    A = 0.15
    q_ex = A * F_FUGA * (flux_nadir(RE + lim) - flux_nadir(o.ra))
    dT = q_ex * h * 3600.0 / C_TH
    rows.append(["%d" % lim, "%.2f" % h, "%.3f" % q_ex, "%.1f" % dT])
out.append("Capacidad termica del conjunto frio supuesta %.0f J/K "
           "(~2 kg de aluminio a 110 K). Radiador de 0,15 m2.\n" % C_TH)
out.append(md_table(["altitud umbral [km]", "h por orbita por debajo",
                     "exceso de carga [W]", "calentamiento acumulado [K]"],
                    rows))

out.append("""
## Veredicto de primer orden sobre IP-2

1. **El area no es el problema.** Desde el apogeo de cualquier HEO, mantener
   150 K con 1 W interno pide ~0,04 m2 y mantener 110 K con 1 W pide ~0,13 m2.
   Son placas de 20 a 36 cm de lado. Caben.
2. **La geometria si lo es.** La temperatura de equilibrio de una placa que
   mira a la Tierra es de 180 a 280 K segun el radio. El radiador tiene que
   mirar al espacio profundo y no ver nunca ni el Sol ni la Tierra. En una HEO
   con apogeo sobre el Artico y el Sol a 24 h en verano, eso obliga a una
   pantalla fija de dos etapas y restringe la actitud. **Es un requisito de
   configuracion, no un componente.**
3. **El perigeo no lo rompe.** Con el radiador apantallado, el exceso de carga
   en el paso bajo es de milivatios y el calentamiento acumulado del conjunto
   frio es de decimas de kelvin. La objecion "solo funciona en apogeo" no
   aplica al radiador; aplicaria a un radiador sin pantalla.
4. **Lo que de verdad decide es el parasito conductivo**, no el radiativo:
   soportes del plano focal, mazo y baffle. Un presupuesto de 0,2-0,5 W de
   parasitos es ambicioso pero no excepcional a 110 K; a 80 K no lo es.
   Por eso un detector T2SL/barrera que opere a 110-150 K cambia la ecuacion
   y uno que exija 80 K no.
5. **Acoplamiento con la radiacion que nadie menciona:** la corriente de
   oscuridad inducida por dano por desplazamiento crece fuertemente con la
   temperatura de operacion. Operar a 150 K en vez de 80 K **amplifica** el
   efecto del dano por protones. Es decir, la opcion "sin criogenerador" solo
   cierra si la orbita saca al satelite del cinturon de protones interno.
   IP-2 y la eleccion de perigeo son la misma decision. [CALCULADO en 08;
   magnitud del acoplamiento: VERIFICAR con datos de proveedor]
""")

txt = "\n".join(out) + "\n"
open("resultados/11_termico.md", "w").write(txt)
print(txt)
