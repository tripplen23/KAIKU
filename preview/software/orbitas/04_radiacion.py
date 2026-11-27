"""
04_radiacion.py  (D10.4)
Entorno de radiacion: travesias de cinturon, tiempo de residencia por capa L
e indice relativo de exposicion.

QUE ES UN CALCULO Y QUE NO:
  [CALCULADO] geometria de la trayectoria en el campo dipolar: L de McIlwain
              aproximada (dipolo centrado alineado), altitud, latitud magnetica,
              radio de cruce del plano ecuatorial, travesias/dia, horas/dia en
              cada banda L. Esto es exacto dentro del modelo dipolar.
  [SUPUESTO]  el "indice de exposicion" pondera el tiempo de residencia por un
              peso por banda L. Los pesos son de ORDEN DE MAGNITUD, no una
              fuente. NO son una dosis en rad(Si). Para una dosis hay que
              correr SPENVIS con AP9/AE9 y una curva de blindaje: eso es
              trabajo de 1-2 dias y esta pendiente [VERIFICAR].

El discriminador fisico real para una HEO esta en el RADIO DE CRUCE DEL PLANO
ECUATORIAL, porque los cinturones atrapados estan concentrados cerca del
ecuador magnetico. Ese numero se calcula exactamente: r_eq = p = a(1-e^2)
cuando el argumento del perigeo es 90 o 270 grados.

Salida: resultados/04_radiacion.md
"""
import math
from orbital import RE, RAD, lshell, md_table
import orbitas_def as od

STEP = 20.0
DAYS = 8
ALT_MIN_TRAP = 1000.0   # km: por debajo, la atmosfera vacia los cinturones [SUPUESTO]

# bandas L: (nombre, Lmin, Lmax, peso de exposicion relativo) [SUPUESTO en el peso]
BANDS = [
    ("Proton interno L1,2-2,5", 1.2, 2.5, 100.0),
    ("Ranura L2,5-3,0",         2.5, 3.0, 5.0),
    ("Electron externo L3-7",   3.0, 7.0, 20.0),
    ("Exterior L>7",            7.0, 1e9, 1.0),
]

orbs = od.build()
ORDER = od.MAIN


def analyse(orb, days=DAYS, step=STEP):
    n = int(days * 86400 / step)
    t_band = [0.0] * len(BANDS)
    cross = 0
    inside = False
    lmin_trap = 1e9
    alt_min = 1e9
    alt_max = 0.0
    for k in range(n):
        x, y, z, r = orb.state_eci(k * step)
        alt = r - RE
        L = lshell(x, y, z)
        trapped = alt > ALT_MIN_TRAP
        alt_min = min(alt_min, alt)
        alt_max = max(alt_max, alt)
        if trapped:
            for j, (_, lo, hi, _) in enumerate(BANDS):
                if lo <= L < hi:
                    t_band[j] += step
                    break
            if L < lmin_trap:
                lmin_trap = L
        core = trapped and (1.2 <= L < 2.5)
        if core and not inside:
            cross += 1
        inside = core
    idx = sum(t_band[j] * BANDS[j][3] for j in range(len(BANDS))) / (days * 86400)
    return dict(h_band=[t / days / 3600.0 for t in t_band],
                cross_day=cross / days, lmin=lmin_trap,
                alt_min=alt_min, alt_max=alt_max, idx=idx)


def r_equator(orb):
    """Radio de cruce del plano ecuatorial (nodos): r = p/(1+e cos nu), nu = -argp."""
    p = orb.a * (1 - orb.e ** 2)
    out = []
    for u in (0.0, math.pi):
        nu = u - orb.argp0
        out.append(p / (1 + orb.e * math.cos(nu)))
    return out


res = {k: analyse(orbs[k]) for k in ORDER}
ref = res["GEO-25E"]["idx"]   # GEO = 1 por referencia

out = ["# 04 — Entorno de radiacion  (D10.4)\n",
       "Generado por `04_radiacion.py`. Dipolo centrado alineado, "
       "L = r/(Re cos^2 lambda). Umbral de atrapamiento: altitud > %d km "
       "[SUPUESTO]. Ventana %d dias, paso %d s.\n"
       % (int(ALT_MIN_TRAP), DAYS, int(STEP)),
       "**El modelo dipolar no reproduce la Anomalia del Atlantico Sur.** "
       "Para LEO eso subestima la dosis; para las HEO es irrelevante porque "
       "su dosis la domina el cruce del ecuador magnetico a radio alto.\n"]

rows = []
for k in ORDER:
    o, r = orbs[k], res[k]
    req = r_equator(o)
    rows.append([o.label,
                 "%d" % round(o.rp - RE), "%d" % round(o.ra - RE),
                 " / ".join("%d" % round(x - RE) for x in req),
                 " / ".join("%.2f" % (x / RE) for x in req),
                 "%.2f" % r["lmin"] if r["lmin"] < 1e8 else "n/a"])
out.append("\n## Geometria frente a los cinturones [CALCULADO]\n")
out.append("`r_eq` = altitud y L en el cruce del plano ecuatorial, donde esta "
           "concentrado el flujo atrapado. Es el numero que decide.\n")
out.append(md_table(["Orbita", "h perigeo [km]", "h apogeo [km]",
                     "altitud en cruce ecuatorial [km]", "L en cruce ecuatorial",
                     "L minima con alt>1000 km"], rows))

rows = []
for k in ORDER:
    o, r = orbs[k], res[k]
    rows.append([o.label, "%.1f" % r["cross_day"]] +
                ["%.2f" % h for h in r["h_band"]] +
                ["%.2f" % (r["idx"] / ref) if r["idx"] > 0
                 else "n/a (SAA, fuera del modelo dipolar)"])
out.append("\n## Residencia por banda L y travesias del cinturon interno\n")
out.append(md_table(
    ["Orbita", "travesias/dia del nucleo L1,2-2,5"] +
    ["h/dia %s" % b[0] for b in BANDS] +
    ["indice exposicion rel. (GEO=1) [SUPUESTO]"], rows))

out.append("\n## Pesos usados en el indice (sustituir por SPENVIS/AP9-AE9)\n")
out.append(md_table(["Banda", "L min", "L max", "peso [SUPUESTO]"],
                    [[b[0], b[1], (b[2] if b[2] < 1e8 else "inf"), b[3]]
                     for b in BANDS]))

out.append("""
## Lectura para un detector MWIR criogenico

Los dos mecanismos que importan no son el mismo:

1. **TID (dosis ionizante total)** — afecta a la electronica de proximidad, al
   ROIC y a la optoelectronica. Se mitiga con blindaje y con componentes
   cualificados. Escala aproximadamente con el indice de la tabla anterior.
2. **DDD (dano por desplazamiento)** — lo causan los protones de >10 MeV del
   cinturon interno. Aumenta la corriente de oscuridad del FPA y genera pixeles
   calientes. **No se mitiga con blindaje razonable**: un proton de 50 MeV
   atraviesa varios mm de aluminio. Se mitiga bajando la temperatura de
   operacion (mas potencia de criogenerador) y con correccion de pixel vivo.
   Para un FPA MWIR, el DDD es el mecanismo que fija la vida util.

Consecuencia directa de la tabla: lo que separa las tres HEO no es la dosis
media, es **donde cruzan el ecuador magnetico**. Una orbita cuyo cruce
ecuatorial este por encima de L~3 no atraviesa el nucleo de protones y el DDD
sobre el FPA deja de ser el riesgo dominante. [CALCULADO]
""")

txt = "\n".join(out) + "\n"
open("resultados/04_radiacion.md", "w").write(txt)
print(txt)
