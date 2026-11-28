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

    print("\nIND-08 anomalía cinemática aprendida (Gaussian MLP)")
    step_lon_11kn = (11.0 * (90.0 / 3600.0)) / 30.0
    tr_steady = [fix(i, 25.0 + i * step_lon_11kn, 60.0, sog=11.0, cog=90.0, dt_s=90)
                 for i in range(8)]
    check(not indicators.ind08_motion_anomaly(tr_steady, TH),
          "no dispara en tránsito rectilíneo a velocidad constante (11,0 kn, dt=90 s)")

    tr_drag = list(tr_steady[:5])
    f4 = tr_drag[-1]
    dlon_d1 = (8.8 * (90.0 / 3600.0)) / 30.0
    dlat_d1 = (1.2 * (90.0 / 3600.0)) / 60.0
    f5 = fix(5, f4["lon"] + dlon_d1, f4["lat"] + dlat_d1, sog=8.88, cog=82.2, dt_s=90)
    tr_drag.append(f5)
    dlon_d2 = (6.8 * (90.0 / 3600.0)) / 30.0
    dlat_d2 = (-1.1 * (90.0 / 3600.0)) / 60.0
    f6 = fix(6, f5["lon"] + dlon_d2, f5["lat"] + dlat_d2, sog=6.89, cog=99.2, dt_s=90)
    tr_drag.append(f6)
    hits8 = indicators.ind08_motion_anomaly(tr_drag, TH)
    check(len(hits8) == 1,
          "dispara con inicio multipaso de arrastre de ancla (2 pasos de frenada/deriva)")
    if hits8:
        ev8 = hits8[0][2]
        check(ev8["radial_z"] > 2.448 and ev8["forcing_source"] == "none",
              "radial_z=%.2f > 2,448 y forcing_source='%s'"
              % (ev8["radial_z"], ev8["forcing_source"]))
        check(ev8["dv_kn"] >= 2.0 and ev8["dt_s"] == 90.0 and ev8["anomaly_steps_in_track"] >= 2,
              "evidencia cinemática coherente (|Δv|=%.2f kn, dt=%.0f s, steps=%d, nll=%.3f)"
              % (ev8["dv_kn"], ev8["dt_s"], ev8["anomaly_steps_in_track"], ev8["nll"]))
        check("prev_dv_east" in ev8 and "prev_dv_north" in ev8 and ev8.get("is_maneuver_vessel") == 0.0,
              "incluye prev_dv_east/north causales e is_maneuver_vessel=0.0 por defecto")
        check(isinstance(ev8.get("has_flow"), bool),
              "incluye bandera booleana has_flow en evidence (%s)" % ev8.get("has_flow"))
    tr_lane = [dict(f, lat=f["lat"] - 0.25) for f in tr_drag]  # lat ~59,75 N (canal principal GoF)
    hits8_lane = indicators.ind08_motion_anomaly(tr_lane, TH)
    check(len(hits8_lane) == 1 and hits8_lane[0][2].get("has_flow") is True,
          "activa has_flow=True sobre el canal de tráfico del golfo de Finlandia (59,75 N)")
    hits8_ferry = indicators.ind08_motion_anomaly(tr_drag, TH, ship_type=60)
    check(len(hits8_ferry) == 1 and hits8_ferry[0][2].get("is_maneuver_vessel") == 1.0,
          "mapea ship_type=60 (pasaje/ferry) a is_maneuver_vessel=1.0")

    hits8_corr = indicators.ind08_motion_anomaly(tr_drag, TH, corridor_idx=idx)
    check(len(hits8_corr) == 1 and hits8_corr[0][2].get("dist_m", 99999) <= 5000.0
          and hits8_corr[0][2].get("corridor") == "TEST-CABLE",
          "dispara a <= 5 km del corredor submarino (dist_m=%.1f m, corridor=%s)"
          % (hits8_corr[0][2].get("dist_m", -1.0) if hits8_corr else -1.0,
             hits8_corr[0][2].get("corridor") if hits8_corr else None))
    tr_drag_far = [dict(f, lat=f["lat"] + 0.10) for f in tr_drag]  # ~11,1 km al norte (> 5 km)
    cnt_far8 = {}
    hits8_far = indicators.ind08_motion_anomaly(tr_drag_far, TH, corridor_idx=idx, counters=cnt_far8)
    check(hits8_far == [] and cnt_far8.get("off_corridor_suppressed_IND-08", 0) >= 1,
          "suprime anomalías a > 5 km de cualquier cable y contabiliza off_corridor_suppressed_IND-08")

    prev_w = os.environ.get("CUSTODY_PATHS_WEIGHTS")
    try:
        os.environ["CUSTODY_PATHS_WEIGHTS"] = "/nonexistent.json"
        cnt8 = {}
        hits8_missing = indicators.ind08_motion_anomaly(tr_drag, TH, counters=cnt8)
        check(hits8_missing == [] and cnt8.get("model_unavailable_IND-08") == 1,
              "degrada a 0 alertas sin excepción cuando CUSTODY_PATHS_WEIGHTS=/nonexistent.json")
    finally:
        if prev_w is None:
            os.environ.pop("CUSTODY_PATHS_WEIGHTS", None)
        else:
            os.environ["CUSTODY_PATHS_WEIGHTS"] = prev_w

    import json as _json
    import tempfile as _tempfile
    from custody import motion as _motion
    corrupt_payloads = [
        {"feature_names": [], "scaler": None, "layers": []},
        {
            "feature_names": ["f%d" % i for i in range(8)],
            "scaler": {"mean": [0.0] * 8, "std": [1.0] * 8},
            "layers": [{"weight": [[1.0, 2.0]], "bias": [0.0]}],
        },
    ]
    corrupt_ok = True
    for cp in corrupt_payloads:
        with _tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            _json.dump(cp, tf)
            tpath = tf.name
        try:
            raised_ve = False
            try:
                _motion.load_model(tpath, refresh=True)
            except ValueError:
                raised_ve = True
            cnt_c = {}
            res_c = indicators.ind08_motion_anomaly(tr_drag, TH, counters=cnt_c, weights_path=tpath)
            if not (raised_ve and res_c == [] and cnt_c.get("model_unavailable_IND-08") == 1):
                corrupt_ok = False
        finally:
            try:
                os.unlink(tpath)
            except OSError:
                pass
    check(corrupt_ok, "degrada a 0 alertas sin excepción ante JSON de pesos corrupto o capas mal formadas")

    tr_malformed = [
        dict(tr_steady[0], cog=float("nan")),
        dict(tr_steady[0]),  # dt=0 duplicado
        dict(tr_steady[1], sog=None),
        dict(tr_steady[2], ts=float("inf")),
        dict(tr_steady[3], lon=float("nan")),
        dict(tr_steady[4], cog=float("nan"), sog=2.01),
        dict(tr_steady[4], ts=tr_steady[4]["ts"] + 90_000, cog=float("nan"), sog=2.01),
    ]
    malformed_ok = True
    try:
        res_m = indicators.ind08_motion_anomaly(
            tr_malformed,
            TH,
            forcing={"wind_speed_kn": None, "wind_from_deg": float("nan"), "current_speed_kn": None},
        )
        malformed_ok = (res_m == [])
    except Exception:
        malformed_ok = False
    check(malformed_ok, "soporta fixes con cog=NaN, ts=Inf, dt=0, sog=None y forcing nulo sin lanzar excepción")

    pm8 = geo.PolygonMask()
    pm8.add_circle(f5["lon"], f5["lat"], 5000, "Puerto de prueba")
    cnt_pm8 = {}
    hits8_pm = indicators.ind08_motion_anomaly(tr_drag, TH, port_mask=pm8, counters=cnt_pm8)
    check(hits8_pm == [] and cnt_pm8.get("port_mask_suppressed_IND-08", 0) >= 1,
          "suprime anomalías dentro de port_mask y contabiliza port_mask_suppressed_IND-08")

    tr_jump = list(tr_steady[:4])
    fj_last = tr_jump[-1]
    # Salto sub-60s (30 s, ~55 km) seguido de continuación que sin guardia dispararía IND-08
    f_subjump = dict(fj_last, ts=fj_last["ts"] + 30_000, lon=fj_last["lon"] + 1.0, sog=8.5)
    f_after1 = dict(fj_last, ts=fj_last["ts"] + 90_000, lon=fj_last["lon"] + 1.005, sog=8.5)
    f_after2 = dict(fj_last, ts=fj_last["ts"] + 180_000, lon=fj_last["lon"] + 2.0, sog=6.5)
    tr_jump.extend([f_subjump, f_after1, f_after2])
    hits7_j = indicators.ind07_impossible_jump(tr_jump, TH)
    hits8_j = indicators.ind08_motion_anomaly(tr_jump, TH)
    check(len(hits7_j) == 1 and hits8_j == [],
          "salto imposible IND-07 (incluso sub-60s) no produce doble disparo en IND-08")

    # Tier-2 Physics-Informed Anchor-Drag Discriminator
    tr_asym_drag = [
        dict(f, heading=(float(f["cog"]) + 14.0) % 360.0 if k >= 3 else float(f["cog"]))
        for k, f in enumerate(tr_drag)
    ]
    tr_asym_drag.extend([
        fix(7, f6["lon"] + dlon_d2 * 0.7, f6["lat"], sog=5.0, cog=90.0, hdg=104.0, dt_s=90),
        fix(8, f6["lon"] + dlon_d2 * 1.4, f6["lat"], sog=4.5, cog=90.0, hdg=104.0, dt_s=90),
    ])
    hits8_asym = indicators.ind08_motion_anomaly(tr_asym_drag, TH, depth_grid=FakeGrid(50.0))
    check(
        len(hits8_asym) == 1
        and hits8_asym[0][2].get("anchor_drag_band") == "HIGH"
        and float(hits8_asym[0][2].get("anchor_drag_prob", 0.0)) >= 0.70
        and hits8_asym[0][2].get("anchor_drag_depth_m") == 50.0
        and hits8_asym[0][2].get("anchor_drag_source") == "physics-sim-tier2",
        "Tier-2 puntúa HIGH (>=0,70) en arrastre asimétrico sobre fondo de 50 m (prob=%s, crab=%s°)"
        % (hits8_asym[0][2].get("anchor_drag_prob") if hits8_asym else None,
           hits8_asym[0][2].get("anchor_drag_crab_deg") if hits8_asym else None),
    )

    tr_sym_slow = [dict(f, heading=float(f["cog"])) for f in tr_drag]
    hits8_sym = indicators.ind08_motion_anomaly(tr_sym_slow, TH, depth_grid=FakeGrid(50.0))
    asym_p = float(hits8_asym[0][2]["anchor_drag_prob"]) if hits8_asym else 1.0
    sym_p = float(hits8_sym[0][2]["anchor_drag_prob"]) if hits8_sym else 1.0
    check(
        len(hits8_sym) == 1
        and sym_p < asym_p - 0.4
        and hits8_sym[0][2].get("anchor_drag_band") == "LOW",
        "Tier-2 puntúa mucho más bajo en desaceleración simétrica HDG==COG (prob=%.3f vs %.3f, band=%s)"
        % (sym_p, asym_p, hits8_sym[0][2].get("anchor_drag_band") if hits8_sym else None),
    )

    prev_t2 = os.environ.get("CUSTODY_PATHS_ANCHOR_WEIGHTS")
    try:
        os.environ["CUSTODY_PATHS_ANCHOR_WEIGHTS"] = "/nonexistent.json"
        hits8_not2 = indicators.ind08_motion_anomaly(tr_asym_drag, TH, depth_grid=FakeGrid(50.0))
        check(
            len(hits8_not2) == 1
            and "anchor_drag_prob" not in hits8_not2[0][2]
            and "anchor_drag_band" not in hits8_not2[0][2],
            "IND-08 degrada limpiamente sin campos Tier-2 cuando CUSTODY_PATHS_ANCHOR_WEIGHTS=/nonexistent.json",
        )
    finally:
        if prev_t2 is None:
            os.environ.pop("CUSTODY_PATHS_ANCHOR_WEIGHTS", None)
        else:
            os.environ["CUSTODY_PATHS_ANCHOR_WEIGHTS"] = prev_t2

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
