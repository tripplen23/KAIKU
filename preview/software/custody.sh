#!/usr/bin/env bash
# Single entrypoint for the whole stack: AIS recorder, build, map viewer.
#
#   ./custody.sh up        start recorder, build if needed, serve the map
#   ./custody.sh down      stop viewer and recorder
#   ./custody.sh status    what is running, how much data, how fresh
#   ./custody.sh build     rebuild the fused layers only
#   ./custody.sh serve     start/stop just the viewer
#   ./custody.sh logs      tail the recorder log
#
# Secrets: software/custody_mvp/secrets.env (chmod 600, gitignored).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
MVP="$HERE/custody_mvp"
REC="$HERE/ais_recorder"

# EL INTERPRETE, TAMBIEN DE LA CONFIGURACION. El entorno con las dependencias
# (h3, paho-mqtt) vive donde dice rutas.toml, fuera del repo. Si no esta, se
# sigue con el python del sistema y lo unico que se pierde es la capa de
# interferencia: que falte una dependencia opcional no puede parar el stack.
# Construirlo:  ./venv.sh
VENV="$(cd "$HERE/../.." && python3 -c 'import rutas; print(rutas.venv())' 2>/dev/null)"
if [ -n "${VENV:-}" ] && [ -x "$VENV/bin/python3" ]; then
  PY="$VENV/bin/python3"
else
  PY="python3"
  VENV=""
fi
# EL ALMACEN SALE DE LA CONFIGURACION, NO DE AQUI.
#
# Esta linea decia  DATA="${AIS_DATA_ROOT:-$HOME/ais_data}"  y luego se lo
# pasaba a la grabadora con --root. O sea que este lanzador era la TERCERA
# opinion sobre donde viven los datos, y la que ganaba: arreglar el defecto de
# recorder.py no servia de nada mientras `./custody.sh up` lo pisara. Es la
# causa concreta de que el 2026-11-13 la grabadora escribiera en ~/ais_data
# mientras la aplicacion miraba en Dropbox -- 4,6 h invisibles.
#
# Ahora se pregunta a custody/paths.py, que lee config/custody.toml, el mismo
# fichero que leen la aplicacion y la grabadora. AIS_DATA_ROOT sigue pisando,
# porque para eso esta, pero solo si alguien la pone a mano.
DATA="${AIS_DATA_ROOT:-$(cd "$HERE/custody_mvp" && "$PY" -c \
  'from custody import paths; print(paths.record() or "")' 2>/dev/null)}"
# Si no se puede preguntar, NO SE ADIVINA. Un defecto de reserva aqui es
# literalmente la segunda opinion que causo el incidente: mejor parar y decir
# que la configuracion no se puede leer.
if [ -z "$DATA" ]; then
  echo "custody.sh: no puedo leer paths.record() de custody_mvp/config/custody.toml." >&2
  echo "            Arregla la configuracion, o pon AIS_DATA_ROOT a mano." >&2
  exit 2
fi

# La salida del build, igual: de la configuracion. Estaba fijada a
# custody_mvp/viewer/data y por eso `status` decia «no build yet» sobre un
# build de 79 ficheros -- el mismo error que con el almacen, en la otra punta.
OUT="$(cd "$HERE/custody_mvp" && "$PY" -c \
  'from custody import paths; print(paths.data())' 2>/dev/null)"
if [ -z "$OUT" ]; then
  echo "custody.sh: no puedo leer paths.data() de custody_mvp/config/custody.toml." >&2
  exit 2
fi
PORT="${CUSTODY_PORT:-8000}"
LOG="$HOME/ais_recorder.log"

c_ok()   { printf '  \033[32m●\033[0m %s\n' "$1"; }
c_bad()  { printf '  \033[31m○\033[0m %s\n' "$1"; }
c_head() { printf '\n\033[1m%s\033[0m\n' "$1"; }

rec_pids() {
  pgrep -af 'recorder\.py' 2>/dev/null | grep -v -e '/bin/bash' -e pgrep | awk '{print $1}'
}
rec_alive() { [ -n "$(rec_pids)" ]; }

rec_start() {
  if rec_alive; then c_ok "recorder already running"; return; fi
  # Sin --root salvo que AIS_DATA_ROOT este puesta a mano: que la grabadora
  # resuelva su propia raiz de la configuracion y lo diga en su log. Pasarle
  # siempre --root es lo que convirtio a este script en una tercera opinion.
  if [ -n "${AIS_DATA_ROOT:-}" ]; then
    ( cd "$REC" && setsid nohup "$PY" -u recorder.py --root "$DATA" \
        >>"$LOG" 2>&1 </dev/null & )
  else
    ( cd "$REC" && setsid nohup "$PY" -u recorder.py \
        >>"$LOG" 2>&1 </dev/null & )
  fi
  sleep 2
  rec_alive && c_ok "recorder started -> $DATA" || c_bad "recorder failed, see $LOG"
}

rec_stop() {
  if ! rec_alive; then c_ok "recorder not running"; return; fi
  "$REC/stop.sh" 60 >/dev/null 2>&1
  rec_alive && c_bad "recorder still alive" || c_ok "recorder stopped cleanly"
}

do_build() {
  c_head "Build"
  ( cd "$MVP" && "$PY" build.py "$@" ) || { c_bad "build failed"; return 1; }
  c_ok "layers rebuilt in $OUT"
}

case "${1:-up}" in
  up)
    c_head "Recorder";      rec_start
    [ -f "$OUT/manifest.json" ] || do_build
    c_head "Viewer";        "$MVP/viewer/serve.sh" start "$PORT"
    c_head "Open";          echo "  http://127.0.0.1:$PORT"
    ;;
  down)
    c_head "Viewer";        "$MVP/viewer/serve.sh" stop "$PORT"
    c_head "Recorder";      rec_stop
    ;;
  build)   shift; do_build "$@" ;;
  serve)   "$MVP/viewer/serve.sh" "${2:-start}" "$PORT" ;;
  logs)    tail -n 40 -f "$LOG" ;;
  status)
    c_head "Python"
    if [ -n "$VENV" ]; then
      c_ok "entorno del proyecto: $VENV"
      "$PY" -c 'import h3' 2>/dev/null && c_ok "h3 (capa gps_interference)" \
                                       || c_bad "h3 falta — ./venv.sh"
    else
      c_bad "sin entorno, uso el python del sistema — ./venv.sh lo construye"
    fi
    c_head "Processes"
    rec_alive && c_ok "recorder (PID $(rec_pids | head -1))" \
               || c_bad "recorder stopped"
    "$MVP/viewer/serve.sh" status "$PORT" | sed 's/^/  /'
    c_head "AIS store  ($DATA)"
    if [ -d "$DATA" ]; then
      echo "  size: $(du -sh "$DATA" 2>/dev/null | cut -f1)"
      ( cd "$REC" && "$PY" aisctl.py --root "$DATA" summary 2>/dev/null \
        | "$PY" -c 'import sys,json;d=json.load(sys.stdin);print("  %s: %d positions, %d MMSI, %.0f%% poll availability"%(d["date"],d["position_reports"],d["unique_mmsi"],d["polls"]["availability_pct"]))' ) \
        2>/dev/null || echo "  (no summary yet)"
    else echo "  not created yet"; fi
    c_head "Build"
    if [ -f "$OUT/manifest.json" ]; then
      "$PY" - "$OUT/manifest.json" <<'PY'
import json,sys,datetime as dt
m=json.load(open(sys.argv[1]))
print("  built:", m["built_utc"])
bad=[k for k,v in m["layers"].items() if v.get("status")!="ok"]
print("  layers ok: %d/%d%s" % (len(m["layers"])-len(bad), len(m["layers"]),
      ("  empty: "+", ".join(bad)) if bad else ""))
PY
    else c_bad "no build yet — run ./custody.sh build"; fi
    c_head "Credentials"
    [ -f "$MVP/secrets.env" ] && c_ok "secrets.env present ($(stat -c%a "$MVP/secrets.env"))" \
      || c_bad "no secrets.env — Sentinel-1 GRD will be skipped"
    # Se comprueba que la clave EXISTE, nunca se imprime su valor.
    for k in CDSE_USERNAME CDSE_PASSWORD GFW_TOKEN; do
      if grep -qE "^[[:space:]]*$k[[:space:]]*=[[:space:]]*[^[:space:]]" "$MVP/secrets.env" 2>/dev/null
      then c_ok "$k set"
      elif [ -n "$(printenv "$k")" ]; then c_ok "$k set (environment)"
      else c_bad "$k missing"; fi
    done
    echo
    ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac
