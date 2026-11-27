"""Que el tiempo real sea real.

Cada prueba de aqui existe por un fallo MEDIDO el 2026-11-13, no por
simetria. Si alguna se puede borrar sin que nada se rompa, es que sobra.

  1. La grabacion se lee de TODOS los almacenes, no del primero que exista.
     Fallo: la grabadora se reinicio con --root ~/ais_data mientras el
     principal seguia en Dropbox. Como el principal existia, el respaldo no
     se consultaba nunca: 4,6 h grabadas e invisibles, sin un solo error.

  2. El motor en vivo pasa la COBERTURA REAL a los indicadores. Fallo:
     pasaba [(inicio, ahora)], o sea «estuvimos escuchando sin parar». Con
     6,5 h de grabadora caida eso convirtio cada casco en una alerta IND-04:
     909 alertas, todas falsas. Con la cobertura del polllog, 157.

  3. La ventana del motor tapa el hueco del build. Fallo: ventana fija de
     6 h con un build de 11 h dejaba 5 h sin buques ni alertas, que es lo
     que la linea de tiempo pintaba hueco.

  4. net.fetch caduca. Fallo: no tenia TTL, asi que «existe el fichero»
     bastaba. Un pronostico de FMI de hace cinco horas se servia como actual
     y habria seguido envejeciendo para siempre.

  5. De CMEMS se elige la cadencia MAS FINA de la version mas alta. Fallo:
     con varias resoluciones de la misma variable ganaba la que apareciera
     primero en el XML, asi que la corriente se pintaba como media de 24 h y
     el nivel del mar como media de 30 dias.
"""
import gzip
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from custody import ais, live, marine, net, paths   # noqa: E402

bad = []


def ok(label, cond, detail=""):
    print(("  ok    " if cond else "  FALLO ") + label + (" · " + detail if detail else ""))
    if not cond:
        bad.append(label)


def _store(root, day, fixes, polls):
    """Un almacen de mentira con la forma real: NDJSON.gz por dia y stream."""
    for stream, recs in (("locations", fixes), ("polllog", polls)):
        d = os.path.join(root, "raw", stream, day[:4], day[5:7])
        os.makedirs(d, exist_ok=True)
        with gzip.open(os.path.join(d, "%s-%s.ndjson.gz" % (stream, day)), "wt") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")


def t_multiroot():
    """1. Dos almacenes, union y deduplicado."""
    tmp = tempfile.mkdtemp()
    try:
        a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
        t0 = 1794500000000
        # El fix t0+1000 esta en LOS DOS: es el mismo casco en el mismo
        # instante oido por dos cadenas de grabacion, y es un fix, no dos.
        _store(a, "2026-11-13", [
            {"mmsi": 1, "lon": 20.0, "lat": 59.0, "timestampExternal": t0},
            {"mmsi": 1, "lon": 20.1, "lat": 59.0, "timestampExternal": t0 + 1000},
        ], [{"stream": "locations", "rx_ms": t0, "http": 200}])
        _store(b, "2026-11-13", [
            {"mmsi": 1, "lon": 20.1, "lat": 59.0, "timestampExternal": t0 + 1000},
            {"mmsi": 1, "lon": 20.2, "lat": 59.0, "timestampExternal": t0 + 2000},
        ], [{"stream": "locations", "rx_ms": t0 + 2000, "http": 200}])

        one, _ = ais.load_fixes(a)
        both, st = ais.load_fixes([a, b])
        ok("un solo almacen ve solo lo suyo", len(one) == 2, "%d fixes" % len(one))
        ok("los dos almacenes se unen y deduplican",
           len(both) == 3 and st["duplicates"] == 1,
           "%d fixes, %d duplicado" % (len(both), st["duplicates"]))
        polls = ais.load_polls([a, b])
        ok("el polllog tambien sale de los dos", len(polls) == 2, "%d polls" % len(polls))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_coverage_not_faked():
    """2. La cobertura que llega a los indicadores es la del polllog.

    Se comprueba sobre el ALMACEN REAL porque el fallo era justo este: el
    motor fabricaba una ventana continua. Si vuelve a hacerlo, la cobertura
    declarada sera igual a la ventana entera y esto lo caza.
    """
    roots = paths.records()
    if not roots:
        print("  --    sin almacen AIS: no se puede comprobar la cobertura")
        return
    eng = live.Engine()
    eng.ctx = {"corridor_idx": None, "grid": None, "port_mask": None, "vessels": {}}
    n = eng.refill()
    win_h = eng.stats["window_h"]
    cov_h = eng.stats["coverage_h"]
    ok("la cobertura sale del polllog, no de la ventana",
       cov_h < win_h * 0.999,
       "ventana %.2f h, cobertura real %.2f h en %d trozos"
       % (win_h, cov_h, eng.stats["coverage_windows"]))
    ok("la ventana tapa el hueco del build",
       eng.stats.get("build_gap_h") is None
       or eng.stats["window_capped"]
       or win_h >= eng.stats["build_gap_h"],
       "hueco %.2f h, ventana %.2f h" % (eng.stats.get("build_gap_h") or 0, win_h))
    ok("la ventana no baja del suelo ni pasa del techo",
       live.WINDOW_H <= win_h <= live.WINDOW_MAX_H, "%.2f h" % win_h)
    ok("hay fixes en la ventana", n > 0, "%d" % n)


def t_window_bounds():
    """3. El calculo de la ventana, sin tocar disco."""
    eng = live.Engine()
    real = live._manifest_end_ms
    try:
        now = int(time.time() * 1000)
        live._manifest_end_ms = lambda: now - 2 * 3600 * 1000
        ok("un build reciente no encoge la ventana por debajo del suelo",
           abs(eng.window_ms() / 3600000.0 - live.WINDOW_H) < 0.01,
           "%.2f h" % eng.window_h)
        live._manifest_end_ms = lambda: now - 1000 * 3600 * 1000
        eng.window_ms()
        ok("un build muy viejo topa y lo DICE",
           eng.window_h == live.WINDOW_MAX_H and eng.stats["window_capped"],
           "%.0f h, capped=%s" % (eng.window_h, eng.stats["window_capped"]))
        live._manifest_end_ms = lambda: now - 11 * 3600 * 1000
        eng.window_ms()
        ok("un hueco de 11 h se cubre entero",
           eng.window_h >= 11.0, "%.2f h" % eng.window_h)
    finally:
        live._manifest_end_ms = real


def t_fetch_expiry():
    """4. max_age: una respuesta vieja deja de servirse."""
    url = "https://example.invalid/custody-test-ttl"
    key = net._key("GET", url, None)
    path = os.path.join(net.CACHE_DIR, key + ".xml")
    os.makedirs(net.CACHE_DIR, exist_ok=True)
    try:
        with open(path, "wb") as fh:
            fh.write(b"viejo")
        os.utime(path, (time.time() - 7200, time.time() - 7200))
        raw, cached = net.fetch(url, ext="xml", max_age=None, retries=0)
        ok("sin max_age se sirve de cache para siempre",
           cached and raw == b"viejo")
        caught = False
        try:
            net.fetch(url, ext="xml", max_age=60, retries=0, timeout=2)
        except Exception:
            caught = True       # sale a la red, y el host no existe
        ok("con max_age vencido NO se sirve la copia vieja", caught)
    finally:
        if os.path.exists(path):
            os.remove(path)


def t_one_store():
    """6. Un almacen declarado, y los de fuera se VIGILAN, no se leen.

    Fallo que lo motiva: `record_fallbacks` leia cualquier directorio que
    existiera, asi que un error de configuracion se tragaba en silencio. Lo que
    hay que proteger ahora es lo contrario -- que un almacen no declarado NO
    entre en records(), y que aun asi se note.
    """
    tmp = tempfile.mkdtemp()
    try:
        main, stray = os.path.join(tmp, "main"), os.path.join(tmp, "stray")
        t0 = 1794500000000
        for r in (main, stray):
            _store(r, "2026-11-13",
                   [{"mmsi": 1, "lon": 20.0, "lat": 59.0, "timestampExternal": t0}],
                   [{"stream": "locations", "rx_ms": t0, "http": 200}])
        saved = dict(paths.CFG["paths"])
        try:
            paths.CFG["paths"]["record"] = main
            paths.CFG["paths"]["record_extra"] = []
            paths.CFG["paths"]["record_watch"] = [stray]
            os.environ.pop("AIS_DATA_ROOT", None)
            rs = paths.records()
            ok("solo se lee el almacen declarado",
               rs == [main], "%d almacen(es)" % len(rs))
            sr = paths.stray_records()
            ok("pero el de fuera se detecta y se nombra",
               len(sr) == 1 and sr[0]["path"] == stray and sr[0]["day_files"] == 1,
               str(sr))
            paths.CFG["paths"]["record_extra"] = [stray]
            ok("declararlo explicitamente SI lo mete, y deja de ser extraviado",
               paths.records() == [main, stray] and paths.stray_records() == [])
        finally:
            paths.CFG["paths"].clear()
            paths.CFG["paths"].update(saved)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_merge_idempotent():
    """7. La fusion no duplica y no necesita parar la grabadora."""
    sys.path.insert(0, os.path.join(ROOT, "..", "ais_recorder"))
    try:
        import merge_store
    except Exception as exc:
        print("  --    sin ais_recorder al lado (%s)" % str(exc)[:60])
        return
    tmp = tempfile.mkdtemp()
    try:
        a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
        t0 = 1794500000000
        _store(a, "2026-11-13",
               [{"mmsi": 1, "lon": 20.0, "lat": 59.0, "timestampExternal": t0}],
               [{"stream": "locations", "rx_ms": t0, "http": 200}])
        _store(b, "2026-11-13",
               [{"mmsi": 1, "lon": 20.0, "lat": 59.0, "timestampExternal": t0},
                {"mmsi": 2, "lon": 21.0, "lat": 59.0, "timestampExternal": t0 + 1000}],
               [{"stream": "locations", "rx_ms": t0 + 1000, "http": 200}])
        quiet = lambda *a, **k: None
        n1 = merge_store.merge(b, a, apply=True, log=quiet)
        fixes, _ = ais.load_fixes(a)
        ok("la fusion copia solo lo que falta",
           n1 == 2 and len(fixes) == 2, "copiados %d, total %d" % (n1, len(fixes)))
        n2 = merge_store.merge(b, a, apply=True, log=quiet)
        fixes2, _ = ais.load_fixes(a)
        ok("y repetirla no duplica nada",
           n2 == 0 and len(fixes2) == 2, "copiados %d, total %d" % (n2, len(fixes2)))
        # Y lo que escriba la grabadora DESPUES se recoge en la pasada siguiente.
        _store_append = _store
        import gzip as _gz
        d = os.path.join(b, "raw", "locations", "2026", "11")
        with _gz.open(os.path.join(d, "locations-2026-11-13.ndjson.gz"), "at") as fh:
            fh.write(json.dumps({"mmsi": 3, "lon": 22.0, "lat": 59.0,
                                 "timestampExternal": t0 + 2000}) + "\n")
        n3 = merge_store.merge(b, a, apply=True, log=quiet)
        ok("un lote escrito despues entra en la pasada siguiente",
           n3 == 1, "copiados %d" % n3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_emodnet():
    """8. La linea base: cadencia leida, y los dos productos distinguidos."""
    from custody import emodnet
    try:
        cat, st = emodnet.catalogue()
    except Exception as exc:
        print("  --    sin capacidades EMODnet en cache (%s)" % str(exc)[:60])
        return
    ok("el catalogo trae las 12 capas", st["layers"] == 12 and not st["missing"],
       "%d capas, faltan %s" % (st["layers"], st["missing"] or "ninguna"))
    emsa = [l for l in cat["layers"] if l["group"] == "baseline"]
    cogea = [l for l in cat["layers"] if l["group"] == "climatology"]
    ok("densidad de rutas (EMSA) y de buques (Cogea) estan las dos",
       emsa and cogea, "%d EMSA, %d Cogea" % (len(emsa), len(cogea)))
    e_end = max(l["time"]["end_ms"] for l in emsa)
    c_end = max(l["time"]["end_ms"] for l in cogea)
    import datetime as _dt
    f = lambda ms: _dt.datetime.fromtimestamp(ms / 1000, _dt.UTC).strftime("%Y-%m")
    # Lo que hace util a la de EMSA es el DESFASE: si las dos acabaran a la vez,
    # alguien habria mezclado los productos.
    ok("la de EMSA va muy por delante de la de Cogea",
       e_end - c_end > 300 * 86400000, "EMSA %s, Cogea %s" % (f(e_end), f(c_end)))
    ok("la de EMSA esta al dia (menos de 90 dias de desfase)",
       (time.time() * 1000 - e_end) < 90 * 86400000,
       "ultimo mes %s" % f(e_end))
    no_t = [l["id"] for l in cat["layers"]
            if l["group"] != "infrastructure" and not (l.get("time") or {}).get("values")]
    ok("toda capa con tiempo declara sus instantes exactos", not no_t,
       ", ".join(no_t) or "8/8")


def t_cfar_demo():
    """10. La explicacion de CFAR se puede volver a ejecutar.

    No es una prueba del detector --- eso lo valida la comparacion con Skylight,
    55 m--- sino de que la EXPLICACION sigue siendo cierta. Una explicacion que
    solo existe en una conversacion se queda vieja y nadie se entera.
    """
    from custody import sardetect
    txt, n = sardetect.demo()
    ok("la demo encuentra los dos barcos, en calma y en mar gruesa",
       n == 2, "%d blancos" % n)
    ok("y ningun umbral global los encuentra los dos",
       "Ninguno vale" in txt)
    # El dial de falsas alarmas, y que el modelo de clutter pese mas que k.
    r6 = sardetect.false_alarm_rate(6)
    g6 = sardetect.false_alarm_rate(6, "gauss")
    ok("k=6 da ~1,5e-6 por pixel con clutter Rayleigh",
       1e-6 < r6 < 2e-6, "%.2e" % r6)
    ok("suponer gaussiano lo baja mas de 1000 veces: el modelo manda",
       r6 / g6 > 1000, "%.0fx" % (r6 / g6))
    ok("y la tasa cae al subir el umbral",
       sardetect.false_alarm_rate(4) > r6 > sardetect.false_alarm_rate(8))


def t_gnss_sources():
    """11. Las dos fuentes de interferencia, y que midan cosas DISTINTAS.

    Lo que hay que proteger no es que respondan --- eso lo dice el build--- sino
    que no se confundan entre si. Si alguien cambiara la de aeronaves por la de
    estaciones creyendo que son intercambiables, la herramienta diria «habia
    interferencia aqui ahora» sobre un dato agregado de hace dos dias.
    """
    from custody import gnssfi, gpsjam
    import datetime as _dt
    try:
        caps = gnssfi.capabilities()
    except Exception as exc:
        print("  --    GNSS-Finland no responde (%s)" % str(exc)[:60])
        return
    ok("la escala del indicador la declara el servicio",
       caps.get("signalQualityIndicators") == {"0": "GOOD", "1": "SATISFACTORY",
                                               "2": "POOR"},
       str(caps.get("signalQualityIndicators")))
    sts = gnssfi.stations(aoi=paths.aoi())
    ok("hay estaciones dentro del area de interes",
       len(sts) >= 25, "%d de 47" % len(sts))
    gulf = [x for x in sts if x["lat"] < 61.5 and x["lon"] > 22]
    ok("y varias bordean el Golfo de Finlandia, que es donde esta el problema",
       len(gulf) >= 5, ", ".join(x["tag"] for x in sorted(
           gulf, key=lambda y: -y["lat"])[:8]))
    ok("la cadencia es de segundos, no de dias",
       (caps.get("obsStoreIntervalSec") or 999) <= 60,
       "%s s" % caps.get("obsStoreIntervalSec"))
    # El peor indicador manda: promediar borraria una banda interferida entre
    # cuatro constelaciones sanas.
    w, where, _ = gnssfi._worst({"GPS": {"numVisibleSatellites": 8,
        "signalsQuality": {"GPS_L1": {"signalId": "GPS_L1", "indicator": 2,
                                      "avgCnr": 30.0, "numSatellites": 7}}},
        "GAL": {"numVisibleSatellites": 9, "signalsQuality": {
            "GAL_E1": {"signalId": "GAL_E1", "indicator": 0, "avgCnr": 48.0}}}})
    ok("una banda degradada entre constelaciones sanas NO se promedia",
       w == 2 and where["signal"] == "GPS_L1", "peor=%s en %s" % (w, where))

    # Y la de aeronaves: que siga llegando tarde, porque de eso depende como se
    # presenta. El dia que llegue al dia habria que cambiar el texto.
    try:
        day, _txt = gpsjam.latest_day()
    except Exception as exc:
        print("  --    GPSJAM no responde (%s)" % str(exc)[:60])
        return
    ok("GPSJAM tiene un dia disponible", bool(day), str(day))
    if day:
        lag = (_dt.date.today() - _dt.date.fromisoformat(day)).days
        ok("y llega con retraso, que es lo que obliga a presentarla como contexto",
           lag >= 1, "%d dia(s) de retraso" % lag)


def t_no_second_opinion():
    """9. Nadie declara su propia ruta del almacen. Una sola fuente.

    Fallo que lo motiva, y es el de verdad: `custody.sh` llevaba
    DATA="${AIS_DATA_ROOT:-$HOME/ais_data}" y se lo pasaba a la grabadora con
    --root. O sea que el lanzador era una TERCERA opinion sobre donde viven los
    datos, y la que ganaba: arreglar el defecto de recorder.py no sirvio de
    nada mientras `./custody.sh up` lo pisara. Igual al otro extremo, con la
    salida del build fijada a custody_mvp/viewer/data.

    Asi que se comprueba lo unico que importa: que ningun fichero del arbol
    escriba una ruta de almacen a mano. Quien la necesite, que la pida.
    """
    import glob as _g
    base = os.path.dirname(ROOT)
    files = ([os.path.join(base, "custody.sh")]
             + _g.glob(os.path.join(base, "ais_recorder", "*.py"))
             + _g.glob(os.path.join(base, "ais_recorder", "*.sh"))
             + _g.glob(os.path.join(ROOT, "*.py"))
             + _g.glob(os.path.join(ROOT, "viewer", "*.py"))
             + _g.glob(os.path.join(ROOT, "custody", "*.py")))
    # paths.py SI declara los defaults: es su trabajo, es la fuente unica.
    allowed = {os.path.join(ROOT, "custody", "paths.py")}
    bad = []
    for f in files:
        if f in allowed or not os.path.exists(f):
            continue
        # Fuera comentarios Y docstrings. La prosa que EXPLICA el fallo cita la
        # ruta vieja a proposito, y una prueba que confunde documentacion con
        # codigo obliga a dejar de documentar, que es lo contrario de lo util.
        tq = ['"' * 3, "'" * 3]
        inside = False
        for n, line in enumerate(open(f, encoding="utf-8", errors="replace"), 1):
            was = inside
            if (line.count(tq[0]) + line.count(tq[1])) % 2:
                inside = not inside
            if was or inside:
                continue
            code = line.split("#")[0]
            # Solo cuenta si la ruta se ASIGNA o se PASA, no si se nombra.
            if "=" not in code and "--root" not in code:
                continue
            if "ais_data" in code and "merged" not in code:
                bad.append("%s:%d" % (os.path.relpath(f, base), n))
            if "viewer/data" in code and "paths" not in code:
                bad.append("%s:%d" % (os.path.relpath(f, base), n))
    ok("nadie fija la ruta del almacen a mano", not bad,
       ", ".join(bad) or "%d ficheros limpios" % len(files))

    # Y que el lanzador siga preguntando por ella.
    sh = open(os.path.join(base, "custody.sh"), encoding="utf-8").read()
    ok("el lanzador pide las rutas a paths.py",
       "paths.record()" in sh and "paths.data()" in sh)
    ok("y no le impone --root a la grabadora sin que se lo pidan",
       'AIS_DATA_ROOT:-}" ]' in sh or "if [ -n \"${AIS_DATA_ROOT:-}\" ]" in sh)


def t_cmems_cadence():
    """5. Se elige la cadencia mas fina de la version mas alta."""
    xml = """
    <Layer><ows:Identifier>P/ds_P1D-m_202411/sea_water_velocity</ows:Identifier>
      <Dimension><ows:Identifier>time</ows:Identifier>
        <Value>2024-01-01T00:00:00Z/2026-11-20T00:00:00Z/P1D</Value></Dimension></Layer>
    <Layer><ows:Identifier>P/ds_PT15M-i_202411/sea_water_velocity</ows:Identifier>
      <Dimension><ows:Identifier>time</ows:Identifier>
        <Value>2024-01-01T00:15:00Z/2026-11-21T12:00:00Z/PT900S</Value></Dimension></Layer>
    <Layer><ows:Identifier>P/ds_PT15M-i_202311/sea_water_velocity</ows:Identifier>
      <Dimension><ows:Identifier>time</ows:Identifier>
        <Value>2021-01-01T00:15:00Z/2026-11-21T12:00:00Z/PT900S</Value></Dimension></Layer>
    """
    got = marine._newest(xml)["sea_water_velocity"]
    ok("gana la cadencia mas fina, no el orden del XML",
       got["step_s"] == 900, "%s s" % got["step_s"])
    ok("pero sin bajar de la version mas alta",
       got["dataset_tag"] == "202411", got["dataset_tag"])
    ok("la ventana temporal se lee de la declaracion",
       got["time"]["start"].startswith("2024-01-01")
       and got["time"]["end"].startswith("2026-11-21"),
       "%s -> %s" % (got["time"]["start"], got["time"]["end"]))

    # Y sobre el catalogo real, si hay cache: que ninguna capa de
    # analisis/pronostico se quede en media diaria o mensual.
    try:
        cat, _ = marine.catalogue()
    except Exception as exc:
        print("  --    sin capacidades CMEMS en cache (%s)" % str(exc)[:60])
        return
    fine = [l for l in cat["layers"] if l["group"] != "reanalysis"]
    coarse = [l["id"] for l in fine if (l.get("step_s") or 0) > 3600]
    # Los recuentos se CUENTAN. Estaban escritos «20» y siguieron diciendo 20
    # al pasar a 22 capas: un mensaje de prueba que miente es peor que ninguno.
    ok("ninguna capa de analisis se sirve como media diaria o mensual",
       not coarse, ", ".join(coarse)
       or "%d capas horarias o mas finas" % len(fine))
    nt = [l["id"] for l in cat["layers"] if not (l.get("time") or {}).get("start_ms")]
    ok("toda capa declara su ventana temporal", not nt,
       ", ".join(nt) or "%d/%d" % (len(cat["layers"]), len(cat["layers"])))
    glob = [l for l in cat["layers"] if l["group"] == "currents_global"]
    ok("el contraste global de Mercator esta y dice su resolucion",
       len(glob) == 2 and all(l["res_km"] == marine.GLOBAL_RES_KM for l in glob)
       and all("merged-uv" in l["layer"] for l in glob),
       "%d capas a %s km" % (len(glob), glob[0]["res_km"] if glob else "-"))


def main():
    print("tiempo real")
    for fn in (t_multiroot, t_one_store, t_merge_idempotent,
               t_coverage_not_faked, t_window_bounds, t_fetch_expiry,
               t_cmems_cadence, t_emodnet, t_cfar_demo, t_gnss_sources,
               t_no_second_opinion):
        try:
            fn()
        except Exception as exc:
            bad.append(fn.__name__)
            print("  FALLO %s -> %s" % (fn.__name__, exc))
    print("\n  %s" % ("%d FALLOS" % len(bad) if bad else "todo verde"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
