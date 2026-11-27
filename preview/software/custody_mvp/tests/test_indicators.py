#!/usr/bin/env python3
"""Pruebas unitarias de los indicadores. Solo stdlib, sin red.

AVISO: las trazas de este fichero son SINTÉTICAS y existen únicamente para
demostrar que cada indicador dispara cuando se le da la señal que dice
detectar, y que NO dispara en los casos límite. No se publican como datos, no
entran en el visor y no se usan para calibrar nada. El visor solo carga lo que
produce build.py a partir de fuentes reales.

Motivo de que esto exista: sobre el almacén AIS real, IND-03 e IND-04 dan 0
porque la ventana grabada es más corta que sus umbrales (60 y 30 min). "Da
cero" y "no funciona" no son lo mismo, y la diferencia hay que demostrarla.

    python3 tests/test_indicators.py      (o ./tests/run.sh)
"""
import sys
import os

# Los tests viven en tests/, el paquete cuelga de la raiz: se sube uno.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from custody import geo, indicators  # noqa: E402

T0 = 1_793_000_000_000
FAIL, OK = [], []


def check(cond, msg):
    (OK if cond else FAIL).append(msg)
    print(("  OK    " if cond else "  FALLO ") + msg)


def fix(i, lon, lat, sog=10.0, cog=90.0, hdg=90, navstat=0, dt_s=60):
    return {"mmsi": 999000001, "ts": T0 + i * dt_s * 1000, "lon": lon, "lat": lat,
            "sog": sog, "cog": cog, "heading": hdg, "rot": 0, "navStat": navstat,
            "posAcc": True, "src": "test", "src_file": "sintetico"}


class FakeGrid:
    def __init__(self, depth):
        self.depth = depth

    def depth_at(self, lon, lat):
        return self.depth


def corridor_index():
    """Un corredor rectilíneo a lo largo de 60,00 N entre 25,0 y 25,6 E."""
    idx = geo.SegmentIndex()
    idx.add_polyline([(25.0, 60.0), (25.6, 60.0)], ("TEST-CABLE", "power", "way/1"))
    return idx


TH = indicators.THRESHOLDS


def main():
    idx = corridor_index()
    grid = FakeGrid(40.0)

    print("\nIND-01 velocidad baja sostenida sobre corredor")
    # 31 fixes de 60 s = 30 min a 3 kn justo sobre el corredor, avanzando
    tr = [fix(i, 25.10 + i * 0.0015, 60.002, sog=3.0) for i in range(31)]
    hits = indicators.ind01_slow_on_corridor(tr, idx, TH, depth_grid=grid)
    check(len(hits) == 1, "dispara con 30 min a 3,0 kn sobre el corredor (%d)" % len(hits))
    if hits:
        check(hits[0][2]["under_power_p1"] is True,
              "P1: p10 de sog >= 2,5 kn => va con maquina, no a la deriva")
    if hits:
        e = hits[0][2]
        check(e["corridor"] == "TEST-CABLE" and e["min_distance_m"] < 300,
              "identifica el corredor y la distancia (%s, %.0f m)"
              % (e["corridor"], e["min_distance_m"]))

    tr = [fix(i, 25.10 + i * 0.006, 60.002, sog=12.0) for i in range(31)]
    check(not indicators.ind01_slow_on_corridor(tr, idx, TH, depth_grid=grid),
          "no dispara en tránsito normal a 12 kn")

    # el caso que rompió la mediana: práctico parado 12 min y luego 12 kn
    tr = ([fix(i, 25.10, 60.002, sog=0.2) for i in range(16)] +
          [fix(16 + i, 25.10 + i * 0.006, 60.002, sog=12.0) for i in range(16)])
    check(not indicators.ind01_slow_on_corridor(tr, idx, TH, depth_grid=grid),
          "no dispara con perfil de práctico (mediana baja, p90 alto)")

    tr = [fix(i, 25.10 + i * 0.0015, 60.002, sog=3.0) for i in range(31)]
    check(not indicators.ind01_slow_on_corridor(tr, idx, TH, depth_grid=FakeGrid(4.0)),
          "no dispara a 4 m de profundidad (suelo de 10 m)")

    mask = geo.PolygonMask()
    mask.add([(25.0, 59.99), (25.3, 59.99), (25.3, 60.01), (25.0, 60.01)], "Puerto de prueba")
    check(not indicators.ind01_slow_on_corridor(tr, idx, TH, depth_grid=grid,
                                                port_mask=mask),
          "no dispara dentro de la máscara de puerto")

    print("\nIND-02 sesgo unilateral COG-HDG (P4 del CTO)")
    # 21 fixes de 60 s = 20 min, proa 35 grados a estribor del rumbo, constante
    tr = [fix(i, 25.1 + i * 0.004, 60.05, sog=6.0, cog=90.0, hdg=125) for i in range(21)]
    hits = indicators.ind02_cog_hdg_bias(tr, TH)
    check(len(hits) == 1, "dispara con +35 grados de sesgo constante 20 min (%d)" % len(hits))
    if hits:
        e = hits[0][2]
        check(e["bias_sign"] == "estribor" and e["sign_consistency"] == 1.0,
              "signo y consistencia correctos (%s, %.2f)" % (e["bias_sign"],
                                                             e["sign_consistency"]))
        check(e["implausible_as_drift"] is False and
              e["metocean_conditioned"] is False,
              "35 grados es deriva plausible y se declara sin condicionar por metocean")

    tr = [fix(i, 25.1 + i * 0.004, 60.05, sog=6.0, cog=90.0, hdg=95) for i in range(21)]
    check(not indicators.ind02_cog_hdg_bias(tr, TH),
          "no dispara con 5 grados (por debajo del sesgo de 8)")

    # EL CASO QUE JUSTIFICA P4: 25 grados de divergencia pero alternando signo.
    # El umbral absoluto de 20 grados lo habria marcado; el sesgo no.
    tr = [fix(i, 25.1 + i * 0.004, 60.05, sog=6.0, cog=90.0,
              hdg=115 if i % 2 == 0 else 65) for i in range(21)]
    cnt = {}
    check(not indicators.ind02_cog_hdg_bias(tr, TH, counters=cnt) and
          cnt.get("sign_flip_suppressed_IND-02", 0) >= 1,
          "no dispara con 25 grados alternando signo (deriva por viento): "
          "esto es lo que el umbral absoluto de 20 grados marcaba mal")

    tr = [fix(i, 25.1 + i * 0.004, 60.05, sog=2.0, cog=90.0, hdg=125) for i in range(21)]
    check(not indicators.ind02_cog_hdg_bias(tr, TH),
          "no dispara a 2,0 kn: P4 exige SOG >= 3 kn")

    tr = [fix(i, 25.1 + i * 0.004, 60.05, sog=6.0, cog=90.0, hdg=265) for i in range(21)]
    hits = indicators.ind02_cog_hdg_bias(tr, TH)
    check(bool(hits) and hits[0][2]["implausible_as_drift"] is True,
          "175 grados se reclasifica como sensor/marcha atras")

    tr = [fix(i, 25.1 + i * 0.004, 60.05, sog=6.0, cog=90.0, hdg=None) for i in range(21)]
    check(not indicators.ind02_cog_hdg_bias(tr, TH),
          "no dispara sin heading (511 -> None)")

    print("\nIND-03 loitering")
    tr = [fix(i, 25.30 + (i % 2) * 0.0005, 60.20, sog=0.3) for i in range(70)]
    hits = indicators.ind03_loitering(tr, TH)
    check(len(hits) == 1, "dispara con 69 min a 0,3 kn sin desplazarse (%d)" % len(hits))

    tr = [fix(i, 25.30, 60.20, sog=0.3, navstat=1) for i in range(70)]
    check(not indicators.ind03_loitering(tr, TH),
          "no dispara con navStat=1 (at anchor, declarado por el buque)")

    tr = [fix(i, 25.30, 60.20, sog=0.3) for i in range(70)]
    pm = geo.PolygonMask()
    pm.add_circle(25.30, 60.20, 2000, "Fondeadero de prueba")
    cnt = {}
    # La clave lleva sufijo de indicador: `port_mask_suppressed_IND-03`. Esta
    # prueba afirmaba la clave sin sufijo y llevaba tiempo fallando sin que
    # nadie lo viera, porque el fichero estaba suelto en la raiz y no habia
    # un comando que lo corriera. Por eso ahora hay tests/run.sh.
    check(not indicators.ind03_loitering(tr, TH, port_mask=pm, counters=cnt) and
          cnt.get("port_mask_suppressed_IND-03") == 1,
          "no dispara en fondeadero y lo contabiliza como supresión")

    # T3: el salto del arranque en frío no puede contar como loitering
    tr = [fix(0, 25.30, 60.20, sog=0.3),
          dict(fix(1, 25.30, 60.20, sog=0.3), ts=T0 + 7200 * 1000)]
    check(not indicators.ind03_loitering(tr, TH),
          "T3: dos fixes separados 2 h no son 2 h de loitering")

    print("\nIND-04 hueco de AIS")
    cov = [(T0 - 60_000, T0 + 7200 * 1000)]
    tr = [fix(0, 25.4, 60.3), fix(1, 25.5, 60.3, dt_s=2400)]   # 40 min
    hits = indicators.ind04_ais_gap(tr, TH, cov, T0 + 2400 * 1000)
    closed = [h for h in hits if h[2]["gap_state"] == "closed"]
    check(len(closed) == 1 and abs(closed[0][2]["gap_min"] - 40.0) < 0.1,
          "dispara hueco cerrado de 40 min (%s)" % [h[2]["gap_min"] for h in closed])

    tr = [fix(0, 25.4, 60.3), fix(1, 25.5, 60.3, dt_s=600)]    # 10 min
    check(not [h for h in indicators.ind04_ais_gap(tr, TH, cov, T0 + 600 * 1000)
               if h[2]["gap_state"] == "closed"],
          "no dispara con 10 min (por debajo del umbral de 30)")

    # T2: el mismo hueco, pero el grabador estaba caído -> no es un hueco de AIS
    tr = [fix(0, 25.4, 60.3), fix(1, 25.5, 60.3, dt_s=2400)]
    cov_split = [(T0 - 60_000, T0 + 60_000), (T0 + 2300 * 1000, T0 + 2500 * 1000)]
    check(not indicators.ind04_ais_gap(tr, TH, cov_split, T0 + 2400 * 1000),
          "T2: el mismo hueco no se emite si el grabador no estuvo escuchando")

    tr = [fix(0, 25.4, 60.3), fix(1, 25.41, 60.3)]
    hits = indicators.ind04_ais_gap(tr, TH, cov, T0 + 60_000 + 3600 * 1000)
    opn = [h for h in hits if h[2]["gap_state"] == "open"]
    check(len(opn) == 1 and opn[0][3] <= 0.5,
          "hueco abierto se emite aparte y con puntuación acotada a 0,5")

    print("\nIND-05 proximidad ponderada por profundidad")
    tr = [fix(i, 25.2 + i * 0.001, 60.0005) for i in range(5)]
    check(len(indicators.ind05_corridor_depth(tr, idx, FakeGrid(40.0), TH)) == 1,
          "dispara a 40 m sobre el corredor")
    check(not indicators.ind05_corridor_depth(tr, idx, FakeGrid(140.0), TH),
          "no dispara a 140 m: fondear ahí no es posible con molinete mercante")
    check(not indicators.ind05_corridor_depth(tr, idx, FakeGrid(5.0), TH),
          "no dispara a 5 m: canal balizado o atraque")
    tr_far = [fix(i, 25.2 + i * 0.001, 60.10) for i in range(5)]   # ~11 km al norte
    check(not indicators.ind05_corridor_depth(tr_far, idx, FakeGrid(40.0), TH),
          "no dispara a 11 km del corredor (umbral 1 NM)")

    print("\nIND-06 encuentro barco a barco (P8 del CTO)")
    def fix2(i, lon, lat, mmsi, sog=0.5, dt_s=60):
        d = fix(i, lon, lat, sog=sog, dt_s=dt_s)
        d["mmsi"] = mmsi
        return d
    # dos buques a ~220 m durante 35 min, ambos a 0,5 kn
    A = [fix2(i, 26.0000, 60.5000, 111111111) for i in range(36)]
    B = [fix2(i, 26.0040, 60.5000, 222222222) for i in range(36)]
    hits = indicators.ind06_encounters({111111111: A, 222222222: B}, TH)
    check(len(hits) == 1, "dispara con dos buques a ~220 m, 35 min, 0,5 kn (%d)" % len(hits))
    if hits:
        e = hits[0][1][2]
        check(e["partner_mmsi"] == 222222222 and e["min_distance_m"] < 300,
              "identifica la pareja y la distancia mínima (%s, %.0f m)"
              % (e["partner_mmsi"], e["min_distance_m"]))
        check(abs(e["duration_min"] - 35.0) < 0.6,
              "duración medida %.1f min" % e["duration_min"])

    # mismos buques, pero a 1,4 km: fuera del umbral de 500 m
    B2 = [fix2(i, 26.0250, 60.5000, 222222222) for i in range(36)]
    check(not indicators.ind06_encounters({111111111: A, 222222222: B2}, TH),
          "no dispara a 1,4 km (umbral 500 m)")

    # cerca pero en movimiento: 8 kn
    B3 = [fix2(i, 26.0040, 60.5000, 222222222, sog=8.0) for i in range(36)]
    check(not indicators.ind06_encounters({111111111: A, 222222222: B3}, TH),
          "no dispara si uno va a 8 kn (umbral 3 kn)")

    # cerca y lentos pero solo 15 min
    A4 = [fix2(i, 26.0, 60.5, 111111111) for i in range(16)]
    B4 = [fix2(i, 26.004, 60.5, 222222222) for i in range(16)]
    check(not indicators.ind06_encounters({111111111: A4, 222222222: B4}, TH),
          "no dispara con 15 min (umbral 30 min)")

    # dentro de fondeadero: suprimido con contador
    pm6 = geo.PolygonMask(); pm6.add_circle(26.002, 60.5, 3000, "Fondeadero")
    c6 = {}
    check(not indicators.ind06_encounters({111111111: A, 222222222: B}, TH,
                                          port_mask=pm6, counters=c6) and
          c6.get("port_mask_suppressed_IND-06") == 1,
          "no dispara en fondeadero y lo contabiliza (advertencia de EMSA)")

    # navStat declarado at anchor por uno de los dos
    B5 = [dict(fix2(i, 26.004, 60.5, 222222222), navStat=1) for i in range(36)]
    check(not indicators.ind06_encounters({111111111: A, 222222222: B5}, TH),
          "no dispara si uno declara navStat=1 (at anchor)")

    print("\nGeometría")
    d, _ = idx.nearest(25.3, 60.0)
    check(d is not None and d < 5.0, "distancia al corredor en su propia línea: %.1f m" % d)
    d, _ = idx.nearest(25.3, 60.01)
    check(abs(d - 1111.0) < 30.0, "0,01 grados de latitud = %.0f m (esperado ~1111)" % d)
    check(abs(geo.angle_diff_deg(350.0, 10.0) - 20.0) < 1e-9,
          "diferencia angular cruza el 0: 350 vs 10 = 20 grados")
    parts = geo.clip_polyline([(20.0, 60.0), (30.0, 60.0)], (22.0, 59.0, 30.5, 60.9))
    check(len(parts) == 1 and abs(parts[0][0][0] - 22.0) < 1e-9,
          "recorte interpola el cruce del borde en lon=22,0 (%.4f)" % parts[0][0][0])

    print("\n=== %d OK, %d FALLOS ===" % (len(OK), len(FAIL)))
    for f in FAIL:
        print("FALLO: " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
