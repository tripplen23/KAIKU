"""
12_cadencia.py
Que cadencia hace falta para que la pista sea defendible frente a los ~30 min
de revisita que seran el estado del arte en 2028 (PierSight, OroraTech) y
frente a los 25 s de stare mas largo del mercado hoy (ICEYE/Umbra Dwell).

Tres criterios, los tres calculables:

  C1. AMBIGUEDAD DE ASOCIACION. Entre dos muestras separadas dt, un blanco de
      velocidad desconocida <= v_max puede estar en cualquier punto de un
      disco de radio v_max*dt. El numero esperado de confusores en esa puerta
      es  N_conf = rho * pi * (v_max*dt)^2,  rho = densidad de buques.
      Criterio: N_conf < 0,1.
      rho se mide, no se inventa: lo dara el grabador AIS de D1
      (Systems Engineer, meri.digitraffic.fi).

  C2. RESOLUCION TEMPORAL DEL EVENTO. El producto forense no es la posicion,
      es el instante de la maniobra (fondeo, deceleracion, giro). Muestreando
      cada dt, el instante del evento solo se acota a +/- dt/2.

  C3. PRECISION DE VELOCIDAD por ajuste lineal de n muestras:
      sigma_v = sigma_p * sqrt(12/(n(n^2-1))) / dt,  con sigma_p = GSD/5
      (centroide subpixel sobre un blanco termico brillante) [SUPUESTO].
      Ojo: este criterio NO favorece la cadencia alta, favorece la base
      temporal larga. Decirlo es mas util que esconderlo.

Salida: resultados/12_cadencia.md
"""
import math
from orbital import md_table

KN = 0.514444          # m/s por nudo
V_MAX = 16.0 * KN      # velocidad maxima plausible de un mercante [SUPUESTO]
V_CRU = 12.0 * KN
GSD = 450.0            # m, GSD_eff MWIR del punto de diseno
SIG_P = GSD / 5.0      # m, error de centroide [SUPUESTO]
DTS = [10, 30, 60, 120, 300, 600, 1800, 3600]
RHOS = [0.001, 0.005, 0.01, 0.05]      # buques/km2

out = ["# 12 — Cadencia necesaria para que la pista sea defendible\n",
       "Generado por `12_cadencia.py`. v_max = %.1f nudos, v crucero = "
       "%.0f nudos, GSD_eff = %.0f m, sigma_posicion = GSD/5 = %.0f m "
       "[SUPUESTO].\n" % (V_MAX / KN, V_CRU / KN, GSD, SIG_P)]

# ---- C1
rows = []
for dt in DTS:
    r_gate = V_MAX * dt / 1000.0        # km
    row = [dt, "%.2f" % r_gate, "%.1f" % (math.pi * r_gate ** 2)]
    for rho in RHOS:
        n = rho * math.pi * r_gate ** 2
        row.append(("%.3f" % n) + (" OK" if n < 0.1 else " **ambiguo**"))
    rows.append(row)
out.append("\n## C1 — Confusores esperados en la puerta de asociacion\n")
out.append("Radio de puerta = v_max * dt. Criterio: < 0,1 confusores "
           "esperados. La densidad real del Golfo de Finlandia y del Barents "
           "sale del grabador AIS de D1; aqui se barre.\n")
out.append(md_table(["dt [s]", "radio de puerta [km]", "area [km2]"] +
                    ["rho=%.3f buques/km2" % r for r in RHOS], rows))

# ---- C2
rows = []
for dt in DTS:
    rows.append([dt, "%.1f" % (dt / 120.0),
                 "%.2f" % (V_CRU * dt / 2 / 1000.0),
                 "OK" if dt <= 240 else "insuficiente"])
out.append("\n## C2 — Resolucion temporal del evento\n")
out.append("Incertidumbre del instante de la maniobra = dt/2, y distancia "
           "recorrida a 12 nudos en ese intervalo. Requisito propuesto: "
           "fechar el evento con +/- 2 min, es decir dt <= 240 s.\n")
out.append(md_table(["dt [s]", "incertidumbre del instante [min]",
                     "deriva a 12 kn en dt/2 [km]", "cumple +/-2 min"], rows))

# ---- C3
rows = []
for dt in DTS:
    row = [dt]
    for T in (600, 1800, 3600):
        n = int(T / dt) + 1
        if n < 3:
            row.append("n<3")
            continue
        sv = SIG_P * math.sqrt(12.0 / (n * (n * n - 1))) / dt
        row.append("n=%d, %.3f m/s (%.2f kn)" % (n, sv, sv / KN))
    rows.append(row)
out.append("\n## C3 — Precision de velocidad por ajuste lineal\n")
out.append("Para una traza rectilinea. **Este criterio no exige cadencia "
           "alta**: con 3 muestras a 30 min se obtiene 0,06 nudos. Es el "
           "argumento que no hay que usar para defender la persistencia.\n")
out.append(md_table(["dt [s]", "traza de 10 min", "traza de 30 min",
                     "traza de 60 min"], rows))

rows = []
for rho in RHOS:
    dtmax = math.sqrt(0.1 / (rho * math.pi)) * 1000.0 / V_MAX
    rows.append(["C1 asociacion sin AIS, rho=%.3f buques/km2" % rho,
                 "<0,1 confusores esperados", "**%.0f s**" % dtmax])
rows.append(["C2 fechar la maniobra a +/-2 min", "dt <= 2*120 s", "**240 s**"])
rows.append(["C3 velocidad a 0,5 kn sobre traza de 30 min",
             "sigma_v < 0,26 m/s", "no restrictivo (>1800 s)"])
TAB_DTMAX = md_table(["Criterio", "Requisito", "dt maximo"], rows)

out.append("""
## Conclusion de requisito temporal

Frente a una revisita de 30 min, el argumento **no** es la precision de
velocidad (C3 demuestra que 30 min bastan si la traza es recta y el blanco
esta identificado). El argumento es doble y es el siguiente:

""" + TAB_DTMAX + """

**Requisito de diseno propuesto: cadencia <= 60 s, objetivo 30 s.**
No "continuo", no 10 s. 60 s cumple los tres criterios con margen y es dos
ordenes de magnitud mas barato en datos y en procesado que 1 s.

Y la frase que hay que poder defender delante de un cliente:

> "Una revisita de 30 minutos te dice que un buque estuvo ahi. Con 60 segundos
> de cadencia te digo cuando redujo a 2 nudos, cuanto tiempo estuvo sobre el
> cable y cuando volvio a acelerar, con el instante fechado a +/-30 s y sin
> depender de que el AIS este encendido."

Eso es lo que no da una constelacion de revisita, por muchos satelites que
tenga: entre pases, la identidad del blanco se pierde. La persistencia no
compra resolucion, compra **continuidad de identidad**.
""")

txt = "\n".join(out) + "\n"
open("resultados/12_cadencia.md", "w").write(txt)
print(txt)
