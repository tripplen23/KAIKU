"""
02_cobertura.py  (D10.2)
Cobertura temporal sobre el Golfo de Finlandia y Utsjoki.

(a) Un satelite: % de tiempo con el>20/40/60 deg, numero de accesos/dia,
    duracion media del acceso, hueco maximo sin acceso, elevacion y distancia
    medias PONDERADAS POR TIEMPO durante el acceso (umbral 40 y 60 deg).
(b) Constelacion para 24/7: N satelites igualmente espaciados a lo largo del
    CICLO DE REPETICION de la traza (no del periodo orbital). Esto importa:
      Molniya  T=11,967 h -> 2 rev / 1 dia sidereo  (2 apogeos, 180 deg aparte)
      TAP      T=15,957 h -> 3 rev / 2 dias sidereos (3 apogeos, 120 deg aparte)
      Tundra   T=23,934 h -> 1 rev / 1 dia sidereo  (1 apogeo, longitud fija)
      GEO      1 rev / 1 dia
    Espaciar por T en vez de por T_rep coloca el segundo satelite en el apogeo
    equivocado (sobre Canada, en el caso Molniya) y da un resultado absurdo.
(c) Para la constelacion minima: peor elevacion y peor distancia del ciclo
    (es el punto de diseno que dimensiona la apertura y el enlace).
(d) LEO/MEO: busqueda Walker-delta P planos x S satelites.

Salida: resultados/02_cobertura.md
"""
import math, json
from orbital import (RE, RAD, OMEGA_E, T_SID, elev_range, site_vec, md_table,
                     walker_delta)
import orbitas_def as od

STEP = 30.0
DAYS_HEO = 8
DAYS_LEO = 14
THRESH = [20.0, 40.0, 60.0]

# ciclo de repeticion de la traza: (revoluciones, dias sidereos)
REPEAT = {
    "GEO-25E":   (1, 1),
    "GEO-0E":    (1, 1),
    "MOLNIYA":   (2, 1),
    "TUNDRA":    (1, 1),
    "TAP-ASBM":  (3, 2),
}

orbs = od.build()


def phased_rep(orb, n, t_rep):
    """n satelites desfasados t_rep/n a lo largo del ciclo de traza repetida."""
    out = []
    for k in range(n):
        dt = k * t_rep / n
        out.append(orb.copy_with(
            M0_deg=(orb.M0 * RAD + orb.dM * dt * RAD) % 360.0,
            raan_deg=(orb.raan0 * RAD - OMEGA_E * dt * RAD) % 360.0))
    return out


def single_stats(orb, lat, lon, days, step=STEP):
    sv = site_vec(lat, lon)
    n = int(days * 86400 / step)
    cnt = {th: 0 for th in THRESH}
    sel = {th: 0.0 for th in THRESH}
    srho = {th: 0.0 for th in THRESH}
    nacc = 0
    in_acc = False
    acc_len = []
    cur = gap = maxgap = 0.0
    for k in range(n):
        el, rho = elev_range(orb.state_ecef(k * step), sv)
        for th in THRESH:
            if el >= th:
                cnt[th] += 1
                sel[th] += el
                srho[th] += rho
        if el >= 40.0:
            if not in_acc:
                in_acc = True
                nacc += 1
                cur = 0.0
                maxgap = max(maxgap, gap)
                gap = 0.0
            cur += step
        else:
            gap += step
            if in_acc:
                in_acc = False
                acc_len.append(cur)
    maxgap = max(maxgap, gap)
    f = {th: cnt[th] / n for th in THRESH}
    mel = {th: (sel[th] / cnt[th] if cnt[th] else 0.0) for th in THRESH}
    mrho = {th: (srho[th] / cnt[th] if cnt[th] else 0.0) for th in THRESH}
    dur = sum(acc_len) / len(acc_len) / 3600.0 if acc_len else 0.0
    return dict(f=f, nacc_day=nacc / days, dur_h=dur, maxgap_h=maxgap / 3600.0,
                mel=mel, mrho=mrho)


def covered(sats, sv, n, step, th):
    for k in range(n):
        t = k * step
        if not any(elev_range(s.state_ecef(t), sv)[0] >= th for s in sats):
            return False
    return True


def worst_case(sats, sv, n, step):
    """Estadistica del satelite SERVIDOR (el de mayor elevacion en cada instante):
    peor elevacion del ciclo, distancia en ese instante, distancia maxima,
    distancia media y percentil 90 de distancia."""
    worst_el, worst_rho = 91.0, 0.0
    rhos = []
    for k in range(n):
        t = k * step
        be, br = -91.0, 0.0
        for s in sats:
            el, rho = elev_range(s.state_ecef(t), sv)
            if el > be:
                be, br = el, rho
        if be < worst_el:
            worst_el, worst_rho = be, br
        rhos.append(br)
    rhos.sort()
    mean_rho = sum(rhos) / len(rhos)
    p90 = rhos[int(0.9 * (len(rhos) - 1))]
    return worst_el, worst_rho, rhos[-1], mean_rho, p90


def min_phased(orb, key, lat, lon, th, nmax=8, step=60.0, cycles=4):
    nrev, nday = REPEAT[key]
    t_rep = nrev * orb.T
    sv = site_vec(lat, lon)
    n = int(cycles * t_rep / step)
    for N in range(1, nmax + 1):
        sats = phased_rep(orb, N, t_rep)
        if covered(sats, sv, n, step, th):
            we, wr, mr, mean_r, p90 = worst_case(sats, sv, n, step)
            return N, we, wr, mr, mean_r, p90
    return (None,) * 6


def min_walker(orb, lat, lon, th, step=60.0, days=1.0, budget=900):
    sv = site_vec(lat, lon)
    n = int(days * T_SID / step)
    best = None
    for P in (2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 21, 24, 28):
        for S in range(1, 25):
            tot = P * S
            if tot > budget or (best and tot >= best[0]):
                break
            if covered(walker_delta(orb, P, S), sv, n, step, th):
                best = (tot, P, S)
                break
    return best


OP = {}   # puntos de operacion exportados para 03_gsd y 05_enlace
out = []
out.append("# 02 — Cobertura temporal  (D10.2)\n")
out.append("Generado por `02_cobertura.py`. Paso %d s. Ventana: %d dias "
           "(traza repetida) / %d dias (LEO-MEO).\n"
           % (int(STEP), DAYS_HEO, DAYS_LEO))
out.append("Ciclos de repeticion de traza usados: Molniya 2 rev/1 dia, "
           "TAP 3 rev/2 dias, Tundra y GEO 1 rev/1 dia. [CALCULADO]\n")

for sk in ("GoF", "Utsjoki"):
    lat, lon, desc = od.SITES[sk]
    rows = []
    for name in od.MAIN:
        o = orbs[name]
        days = DAYS_LEO if name.startswith(("LEO", "MEO")) else DAYS_HEO
        st = single_stats(o, lat, lon, days)
        if sk == "GoF":
            OP[name] = dict(label=o.label, f20=st['f'][20.0], f40=st['f'][40.0],
                            f60=st['f'][60.0], el_mean=st['mel'][40.0],
                            R_mean40=st['mrho'][40.0], R_mean60=st['mrho'][60.0],
                            maxgap_h=st['maxgap_h'], nacc_day=st['nacc_day'],
                            dur_h=st['dur_h'])
        rows.append([
            o.label,
            "%.2f" % (100 * st['f'][20.0]),
            "%.2f" % (100 * st['f'][40.0]),
            "%.2f" % (100 * st['f'][60.0]),
            "%.1f" % st['nacc_day'],
            "%.2f" % st['dur_h'],
            "%.1f" % st['maxgap_h'],
            "%.0f" % st['mel'][40.0] if st['mel'][40.0] else "-",
            "%d" % round(st['mrho'][40.0]) if st['mrho'][40.0] else "-",
            "%d" % round(st['mrho'][60.0]) if st['mrho'][60.0] else "-",
            ("%d" % math.ceil(1.0 / st['f'][40.0])) if st['f'][40.0] > 0 else "n/a",
        ])
    out.append("\n## %s — %s\n" % (sk, desc))
    out.append(md_table(
        ["Orbita", "%t el>20", "%t el>40", "%t el>60", "accesos/dia",
         "dur. media acc>40 [h]", "hueco max [h]", "el media (>40) [deg]",
         "dist media (>40) [km]", "dist media (>60) [km]",
         "cota N>=1/f (el>40)"], rows))

# ---------------------------------------------------------- constelaciones HEO
out.append("\n## Constelacion de traza repetida: N minimo para 24/7\n")
out.append("N satelites espaciados T_rep/N con correccion de nodo "
           "-omega_e*dt. Verificado sobre 4 ciclos completos, paso 60 s. "
           "`el_min` y `R(el_min)` son el peor instante del ciclo: ese es el "
           "punto de diseno de apertura y enlace, no el apogeo.\n")
for sk in ("GoF", "Utsjoki"):
    lat, lon, desc = od.SITES[sk]
    rows = []
    for name in ("GEO-25E", "MOLNIYA", "TUNDRA", "TAP-ASBM"):
        o = orbs[name]
        r = []
        for th in (40.0, 60.0, 70.0):
            res = min_phased(o, name, lat, lon, th)
            N = res[0]
            r.append("%d" % N if N else ">8")
            if th == 60.0:
                if N:
                    we, wr, mr, mean_r, p90 = res[1], res[2], res[3], res[4], res[5]
                    if sk == "GoF":
                        OP[name].update(N60=N, el_min=we, R_med_serv=mean_r,
                                        R_p90_serv=p90, R_max_serv=mr)
                    det = "el_min=%.1f deg · R med=%d · R p90=%d · R max=%d" % (
                        we, round(mean_r), round(p90), round(mr))
                else:
                    det = "-"
        rows.append([o.label] + r + [det])
    out.append("\n### %s\n" % desc)
    out.append(md_table(["Orbita", "N (el>40)", "N (el>60)", "N (el>70)",
                         "con N(el>60): elevacion minima y distancia del satelite servidor [km]"], rows))

# ---------------------------------------------------------- Walker LEO/MEO
lat, lon, _ = od.SITES["GoF"]
rows = []
for name in ("LEO-SSO-600", "LEO-ALTA-2000", "MEO-8000", "MEO-20000"):
    o = orbs[name]
    b40 = min_walker(o, lat, lon, 40.0)
    b60 = min_walker(o, lat, lon, 60.0)
    rows.append([o.label,
                 ("%d (P=%d x S=%d)" % b40) if b40 else ">900",
                 ("%d (P=%d x S=%d)" % b60) if b60 else ">900"])
    OP[name].update(walker40=b40[0] if b40 else None,
                    walker60=b60[0] if b60 else None)
out.append("\n## Constelacion Walker-delta: total minimo para cobertura "
           "continua del Golfo de Finlandia\n")
out.append("Rejilla P en {2,3,4,5,6,8,10,12,15,18,21,24,28} x S en {1..24}, "
           "1 dia sidereo, paso 60 s, techo 900 satelites. Es el minimo SOBRE "
           "LA REJILLA, no un optimo global: un diseno dedicado puede bajarlo "
           "~20-30%. El orden de magnitud es el resultado.\n")
out.append(md_table(["Orbita", "Total min. el>40", "Total min. el>60"], rows))

txt = "\n".join(out) + "\n"
open("resultados/02_cobertura.md", "w").write(txt)
json.dump(OP, open("resultados/puntos_operacion.json", "w"), indent=1)
print(txt)
