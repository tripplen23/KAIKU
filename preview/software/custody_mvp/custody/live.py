"""Motor de alertas en tiempo de ejecucion.

POR QUE EXISTE.

Las alertas se calculaban SOLO en el build. Eso convierte una herramienta de
vigilancia en una de informes: con un build de 42 horas, la pregunta «que esta
pasando ahora» se respondia con lo que pasaba anteayer. El valor del producto
esta en disparar en el momento en que se descubre, no en describirlo despues.

QUE SE MUEVE Y QUE NO.

Los siete indicadores se ejecutan aqui, en el servidor, con EL MISMO
custody/indicators.py que usa el build. No hay una segunda implementacion en
JavaScript: dos copias de una regla de deteccion es como se consigue que la
demo y el informe no coincidan, y ya hemos visto en este proyecto lo caro que
sale duplicar logica (la paleta de profundidad, la clasificacion de cuencas).

El CONTEXTO sigue siendo trabajo de build, y con razon: los cables, la
batimetria, la mascara de puertos y la costa no cambian entre un sondeo y el
siguiente. Se cargan una vez al arrancar --0,1 s-- y se reutilizan.

COSTE MEDIDO, sobre este almacen:

    ventana   fixes    trazas   alertas   tiempo
      1 h    21.679      590      163     0,63 s
      6 h   120.369      626      524     3,97 s

O sea: una pasada completa sobre seis horas cuesta cuatro segundos, y la
grabadora escribe cada sesenta. Sobra margen.

POR QUE UNA VENTANA MOVIL Y NO TODO EL ALMACEN.

Recorrer las 794.388 posiciones cuesta 4,4 s solo en leerlas. Pero ningun
indicador mira mas atras de su propia ventana --la mas larga es la de IND-01,
treinta minutos sostenidos-- asi que evaluar sobre las ultimas horas da el
mismo resultado que evaluar sobre todo, a una fraccion del coste. La ventana
se fija con holgura sobre la mas larga, no al minimo.
"""
import json
import logging
import os
import threading
import time

from custody import ais, aishub, bathymetry, geo, indicators, paths

LOG = logging.getLogger("custody.live")

WINDOW_H = 6          # ventana MINIMA de evaluacion
WINDOW_MAX_H = 36     # tope duro: mas alla de esto hay que compilar
POLL_S = 3            # cada cuanto se MIRA si el almacen cambio (solo stat)
IDLE_S = 300          # reevaluar aunque nada cambie, por si acaso


def _manifest_end_ms():
    """Hasta donde llega lo COMPILADO, leido del manifest del build.

    El motor tiene que cubrir desde ahi hasta ahora, no una ventana fija: con
    una de seis horas y un build de once, quedaba un agujero de cinco horas
    sin buques ni alertas que la linea de tiempo pintaba hueco y el usuario
    leia, con razon, como «hay que compilar otra vez».
    """
    try:
        with open(paths.data("manifest.json")) as fh:
            return int((json.load(fh).get("time") or {}).get("dataset_end_ms") or 0)
    except Exception:
        return 0


class Engine:
    def __init__(self, aoi=None):
        self.aoi = aoi or paths.aoi()
        self.ctx = {}
        self.fixes = []            # ventana movil, ordenada por ts
        self.coverage = []         # ventanas REALES de sondeo, del polllog
        self.alerts = []           # ultimo resultado completo
        self.seen = {}             # (mmsi, indicator) -> primera vez vista
        self.at = 0                # cuando se evaluo
        self.last_ts = 0           # fix mas reciente ingerido
        self.tracks = {}           # mmsi -> fixes, la ventana como trazas
        self.vessels = {}
        self.sig = None            # firma del almacen: cambia = hay dato nuevo
        self.window_h = WINDOW_H
        self.stats = {}
        self.lock = threading.Lock()

    # ------------------------------------------------------------ contexto
    def load_context(self):
        """Lo que no cambia entre sondeos. Una vez, al arrancar."""
        t0 = time.time()
        D = paths.data
        ci = geo.SegmentIndex()
        try:
            for f in json.load(open(D("corridors_trunk.geojson")))["features"]:
                g = f["geometry"]
                segs = (g["coordinates"] if g["type"] == "MultiLineString"
                        else [g["coordinates"]])
                for seg in segs:
                    ci.add_polyline(seg, f["properties"].get("name") or "?")
        except Exception as exc:
            LOG.warning("sin corredores: IND-01 e IND-05 no podran disparar (%s)", exc)

        grid = None
        for cand in (paths.cache("depth_grid_003.json"), D("depth_grid.json")):
            try:
                grid = bathymetry.DepthGrid.from_json(json.load(open(cand)))
                break
            except Exception:
                continue

        pm = geo.PolygonMask()
        try:
            for f in json.load(open(D("ports.geojson")))["features"]:
                g = f["geometry"]
                if g["type"] == "Polygon":
                    pm.add(g["coordinates"][0], f["properties"].get("name") or "port")
        except Exception as exc:
            LOG.warning("sin mascara de puertos (%s)", exc)

        # Los metadatos estaticos salen del ALMACEN (mensaje 5 del AIS), no
        # de vessel_info.json: ese es el dossier enriquecido y tiene otra
        # forma. Sin esto las alertas salian como «MMSI 265048080 · type n/a»,
        # que es exactamente lo que un operador no puede usar.
        vessels = {}
        try:
            roots = paths.records()
            if roots:
                vessels = ais.load_vessels(roots)
        except Exception as exc:
            LOG.warning("sin metadatos de buque: las alertas saldran sin nombre (%s)", exc)

        self.ctx = {"corridor_idx": ci, "grid": grid,
                    "port_mask": pm if pm.polys else None, "vessels": vessels}
        self.stats["context_s"] = round(time.time() - t0, 2)
        self.stats["corridor_segments"] = len(ci.segs)
        self.stats["port_polygons"] = len(pm.polys)
        self.stats["vessels_named"] = len(vessels)
        LOG.info("contexto cargado en %.2f s: %d segmentos de cable, %d puertos",
                 self.stats["context_s"], len(ci.segs), len(pm.polys))
        return self.ctx

    # ------------------------------------------------------------ ingesta
    def _day_files(self, root, days=2):
        """Los ficheros de los ultimos dias, no el almacen entero.

        Releer las 794.388 posiciones cada minuto son 4,4 s tirados: la
        ventana movil nunca mira mas de unas horas atras.
        """
        base = os.path.join(root, "raw", "locations")
        out = []
        for dirpath, _, names in os.walk(base):
            for n in sorted(names):
                if n.endswith(".gz"):
                    out.append(os.path.join(dirpath, n))
        return out[-days:]

    def window_ms(self):
        """Cuanto hacia atras se evalua, AHORA.

        No es una constante. El motor tiene que tapar exactamente el hueco que
        deja el build: desde donde termino lo compilado hasta este instante.
        Con una ventana fija de 6 h y un build de 11 h quedaban 5 h sin buques
        ni alertas --- ni del build, que no habia llegado, ni del motor, que no
        miraba tan atras--- y eso es lo que la linea de tiempo pintaba hueco.

        Suelo: WINDOW_H, porque ningun indicador mira mas de 30 min atras y
        bajar de ahi no ahorra nada util.
        Techo: WINDOW_MAX_H. Pasado ese punto el coste crece sin que el valor
        lo haga, y lo correcto es compilar. El motor lo DICE en vez de
        quedarse corto en silencio.
        """
        built = _manifest_end_ms()
        now = int(time.time() * 1000)
        need_h = (now - built) / 3600000.0 if built else WINDOW_H
        # Un poco de solape con el build: si cortaramos justo en su borde, una
        # traza partida por el corte perderia el fix anterior y con el la
        # velocidad y el rumbo de entrada.
        h = max(WINDOW_H, min(WINDOW_MAX_H, need_h + 0.5))
        self.window_h = round(h, 2)
        self.stats["window_h"] = self.window_h
        self.stats["built_to_ms"] = built
        self.stats["build_gap_h"] = round(need_h, 2) if built else None
        self.stats["window_capped"] = bool(built and need_h + 0.5 > WINDOW_MAX_H)
        return int(h * 3600 * 1000)

    def store_signature(self):
        """Firma barata del almacen: (ruta, tamano, mtime) del ultimo fichero
        de cada stream. Solo `stat`, sin abrir nada.

        Es lo que convierte el motor de SONDEO a EVENTO. Antes dormia 60 s
        entre pasadas, asi que un fix nuevo podia esperar un minuto entero
        antes de ser comprobado. Ahora se mira la firma cada POLL_S --- unas
        pocas llamadas a stat, coste despreciable--- y en cuanto cambia se
        evalua. El retardo deja de ser «hasta 60 s» y pasa a ser el tiempo de
        la propia evaluacion.
        """
        out = []
        for root in paths.records():
            base = os.path.join(root, "raw", "locations")
            newest = None
            for dirpath, _, names in os.walk(base):
                for n in names:
                    if not n.endswith(".gz"):
                        continue
                    f = os.path.join(dirpath, n)
                    try:
                        st = os.stat(f)
                    except OSError:
                        continue
                    if newest is None or st.st_mtime > newest[1]:
                        newest = (f, st.st_mtime, st.st_size)
            if newest:
                out.append(newest)
        return tuple(out)

    def refill(self):
        """Rellena la ventana movil desde el almacen, y de AISHub si hay clave.

        TODOS los almacenes, no el primero que exista. El 2026-11-13 la
        grabadora se reinicio apuntando al respaldo (~/ais_data) mientras el
        principal seguia en Dropbox: 4,6 h grabadas que la aplicacion no podia
        ver, sin un solo error en el log. Ver paths.records().

        AISHub es una SEGUNDA FUENTE, no un sustituto. Nuestra cobertura es
        el 21 % del AOI y muere hacia los 57 N; su red tiene 32 estaciones
        justo en ese hueco, Gotland incluida. Los fixes llegan ya en la forma
        de custody/ais.py, asi que se mezclan sin traducir.

        Hoy devuelve vacio porque la clave exige receptor propio aprobado. El
        cliente esta montado para que el dia que exista sea pegar una linea
        en secrets.env.
        """
        roots = paths.records()
        if not roots:
            raise RuntimeError("no hay almacen AIS")
        cut = int(time.time() * 1000) - self.window_ms()
        fixes, fst = ais.load_fixes(roots, bbox=self.aoi)
        fixes = [f for f in fixes if f["ts"] >= cut]
        n_own = len(fixes)

        n_hub = 0
        try:
            hub, hst = aishub.fetch_vessels(self.aoi)
            self.stats["aishub"] = hst
            if hst.get("ok"):
                # Deduplicar contra lo nuestro: las dos redes oyen al mismo
                # buque en la misma zona y contarlo dos veces falsearia tanto
                # la densidad como cualquier indicador que mire huecos.
                seen = {(f["mmsi"], f["ts"]) for f in fixes}
                for f in hub:
                    if f["ts"] >= cut and (f["mmsi"], f["ts"]) not in seen:
                        fixes.append(f)
                        n_hub += 1
        except Exception as exc:
            self.stats["aishub"] = {"ok": False, "reason": "error",
                                    "note": str(exc)[:160]}

        fixes.sort(key=lambda f: f["ts"])
        with self.lock:
            self.fixes = fixes
            self.last_ts = fixes[-1]["ts"] if fixes else 0
        self.stats["fixes_own"] = n_own
        self.stats["fixes_aishub"] = n_hub
        self.stats["stores"] = list(roots)
        # Grabacion fuera del almacen declarado. No se lee --- leerla por
        # detras es como se acabo con los datos dispersos--- pero se dice, para
        # que el visor pueda avisar en vez de disimular.
        try:
            self.stats["strays"] = paths.stray_records()
        except Exception:
            self.stats["strays"] = []
        self.stats["store_files"] = fst.get("files")
        self.stats["window_start_ms"] = cut

        # LA COBERTURA REAL, no la ventana.
        #
        # Esto pasaba [(cut, now)] a los indicadores: una sola ventana
        # continua, o sea la afirmacion «estuvimos escuchando todo el rato».
        # IND-04 dispara cuando un buque deja de emitir DENTRO de cobertura,
        # asi que mentir ahi convierte cada parada de la grabadora en una
        # alerta por buque. Medido hoy, con 6,5 h de grabadora caida:
        # 909 alertas IND-04 -- una por casco, todas falsas.
        #
        # El polllog registra cuando estabamos sondeando de verdad. Es la
        # misma correccion que ya aplicaba el build (T2); faltaba aqui.
        try:
            polls = ais.load_polls(roots)
            wins = [w for w in ais.coverage_windows(polls) if w[1] >= cut]
            self.coverage = [(max(a, cut), b) for a, b in wins] or [(cut, cut)]
        except Exception as exc:
            LOG.warning("sin polllog: IND-04 no se puede corregir por cobertura (%s)", exc)
            self.coverage = [(cut, int(time.time() * 1000))]
        self.stats["coverage_windows"] = len(self.coverage)
        self.stats["coverage_h"] = round(
            sum(b - a for a, b in self.coverage) / 3600000.0, 2)
        return len(fixes)

    # ----------------------------------------------------------- evaluar
    def evaluate(self):
        """Corre los siete indicadores sobre la ventana. Devuelve stats."""
        t0 = time.time()
        with self.lock:
            fixes = list(self.fixes)
        if not fixes:
            return {"fixes": 0, "alerts": 0}
        now = max(f["ts"] for f in fixes)
        cut = now - int(self.window_h * 3600 * 1000)
        tracks = ais.build_tracks(fixes)
        # La cobertura REAL del polllog, recortada a la ventana. Pasar
        # [(cut, now)] afirmaba que estuvimos escuchando sin parar y convertia
        # cada caida de la grabadora en una alerta IND-04 por casco.
        cov = [(max(a, cut), min(b, now)) for a, b in (self.coverage or [])
               if b >= cut and a <= now] or [(cut, now)]
        alerts, st = indicators.run(
            tracks, self.ctx["corridor_idx"], self.ctx["grid"],
            cov, now, port_mask=self.ctx["port_mask"],
            vessels=self.ctx["vessels"], aoi=self.aoi)

        # Que es NUEVO. Sin esto una alerta vieja se notifica en cada ciclo y
        # el operador deja de mirar los avisos, que es lo peor que puede
        # pasarle a una herramienta de vigilancia.
        nuevas = 0
        ahora = int(time.time() * 1000)
        for a in alerts:
            p = a.get("properties", a)
            # El compañero forma parte de la identidad en IND-06: un buque
            # junto a DOS barcos distintos son dos encuentros, no uno
            # repetido, y con la clave (mmsi, indicador) el segundo nunca se
            # habría anunciado como nuevo.
            ev = p.get("evidence") or {}
            key = (p.get("mmsi"), p.get("indicator"), ev.get("partner_mmsi"))
            if key not in self.seen:
                self.seen[key] = ahora
                p["first_seen_ms"] = ahora
                p["is_new"] = True
                nuevas += 1
            else:
                p["first_seen_ms"] = self.seen[key]
                p["is_new"] = False

        with self.lock:
            self.alerts = alerts
            self.tracks = tracks
            self.at = ahora
        st.update({"fixes": len(fixes), "tracks": len(tracks),
                   "alerts": len(alerts), "new": nuevas,
                   "eval_s": round(time.time() - t0, 2),
                   "newest_fix_ms": now, "window_h": self.window_h})
        self.stats.update(st)
        return st

    def geojson(self):
        with self.lock:
            return indicators.to_geojson(list(self.alerts), {"mode": "live"})

    def tracks_geojson(self, since=None):
        """La ventana como trazas, en el MISMO formato que tracks.geojson.

        Esto es lo que hace que la linea de tiempo deje de pedir un build. El
        visor las fusiona en su propio HIST, asi que el deslizador, la
        instantanea, el historial de un buque y los recuentos cubren tambien
        lo que todavia no se ha compilado. Mismo constructor que el build
        (ais.tracks_geojson), para que una derrota no cambie de forma al
        cruzar esa frontera.
        """
        with self.lock:
            tracks = {m: list(v) for m, v in self.tracks.items()}
            vessels = self.ctx.get("vessels") or {}
        gap_ms = indicators.THRESHOLDS["max_gap_s"] * 1000
        fc, st = ais.tracks_geojson(tracks, vessels, gap_ms, since=since)
        # DONDE EMPIEZA LA VENTANA, no donde empieza este lote.
        #
        # El visor necesita saber si el motor LLEGA hasta el borde del build,
        # y eso no se puede deducir de los fixes recibidos: si la grabadora
        # estuvo parada, el fix mas antiguo de la ventana es posterior a su
        # inicio y parecia un hueco de cobertura cuando era un hueco de
        # grabacion. Son cosas distintas y el aviso que corresponde tambien.
        fc["properties"] = {"mode": "live", "since_ms": since,
                            "window_h": self.window_h,
                            "window_start_ms": self.stats.get("window_start_ms"),
                            "built_to_ms": self.stats.get("built_to_ms"),
                            "window_capped": self.stats.get("window_capped"),
                            "newest_fix_ms": self.last_ts, **st}
        return fc

    # -------------------------------------------------------------- bucle
    def run_forever(self, poll_s=POLL_S, on_cycle=None):
        """Dispara cuando LLEGA el dato, no cuando vence un temporizador.

        El bucle anterior dormia 60 s entre pasadas: con la grabadora
        escribiendo tambien cada 60 s, un fix podia esperar un minuto antes de
        ser comprobado, y en el peor caso la alerta salia con un minuto largo
        de retraso. Una herramienta de vigilancia con retraso es una
        herramienta de informes.

        Ahora se mira la firma del almacen --- unas pocas llamadas a stat---
        cada POLL_S segundos y se evalua en cuanto cambia. IDLE_S fuerza una
        pasada aunque nada se mueva: la ventana avanza con el reloj, asi que
        lo que ya no cabe en ella tiene que dejar de contar.
        """
        self.load_context()
        last_run = 0
        while True:
            try:
                sig = self.store_signature()
                fresh = sig != self.sig
                if fresh or time.time() - last_run > IDLE_S:
                    self.sig = sig
                    last_run = time.time()
                    t0 = time.time()
                    n = self.refill()
                    st = self.evaluate()
                    st["trigger"] = "new data" if fresh else "idle refresh"
                    st["cycle_s"] = round(time.time() - t0, 2)
                    self.stats.update(st)
                    LOG.info("%s: %d fixes, %d trazas, %d alertas (%d nuevas) "
                             "en %.2f s, ventana %.1f h",
                             st["trigger"], n, st.get("tracks", 0),
                             st.get("alerts", 0), st.get("new", 0),
                             st.get("eval_s", 0), self.window_h)
                    if on_cycle:
                        on_cycle(st)
            except Exception as exc:
                LOG.warning("ciclo fallido: %s", exc)
            time.sleep(poll_s)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    e = Engine()
    e.load_context()
    print("fixes en ventana:", e.refill())
    st = e.evaluate()
    print(json.dumps({k: v for k, v in st.items()
                      if k in ("fixes", "tracks", "alerts", "new", "eval_s",
                               "window_h")}, indent=1))
    import collections
    c = collections.Counter(a.get("indicator") for a in e.alerts)
    for k in sorted(c):
        print("   %s  %4d" % (k, c[k]))
