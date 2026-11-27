#!/usr/bin/env bash
# Visor del mapa.  Uso: ./serve.sh start|stop|status|restart|cache|purge [puerto]
#
# Sirve con server.py, que es multihilo y cachea en disco las teselas de
# Planetary Computer. Ver la cabecera de server.py para qué se cachea y
# durante cuánto.
set -u
cd "$(dirname "$0")"
PORT="${2:-8000}"
PIDF=".serve.$PORT.pid"

alive() { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }

case "${1:-start}" in
  start)
    if alive; then echo "ya corre en :$PORT (PID $(cat "$PIDF"))"; exit 0; fi
    setsid nohup python3 server.py "$PORT" \
      > ".serve.$PORT.log" 2>&1 < /dev/null &
    echo $! > "$PIDF"; sleep 1
    if alive; then
      echo "visor arriba  ->  http://127.0.0.1:$PORT  (PID $(cat "$PIDF"))"
      head -1 ".serve.$PORT.log"
    else echo "no arrancó, mira .serve.$PORT.log"; exit 1; fi ;;
  stop)
    if alive; then kill "$(cat "$PIDF")" && echo "parado (PID $(cat "$PIDF"))";
    else echo "no corre en :$PORT"; fi
    rm -f "$PIDF" ;;
  restart) "$0" stop "$PORT"; sleep 1; "$0" start "$PORT" ;;
  status)
    if alive; then echo "corre en :$PORT (PID $(cat "$PIDF"))";
    else echo "parado"; fi ;;
  cache)
    if alive; then
      curl -s "http://127.0.0.1:$PORT/cache/stats" | python3 -c '
import json,sys
d=json.load(sys.stdin)
print("cache en %s" % d["dir"])
print("  %d ficheros, %.1f MB" % (d["files"], d["bytes"]/1e6))
for k,v in sorted(d["by_kind"].items()):
    print("    %-6s %5d ficheros  %7.1f MB" % (k, v["files"], v["bytes"]/1e6))
tot=d["hit"]+d["miss"]
print("  esta sesión: %d aciertos, %d fallos, %d errores%s"
      % (d["hit"], d["miss"], d["error"],
         ("  (%.0f%% desde disco)" % (100*d["hit"]/tot)) if tot else ""))'
    else
      du -sh ../cache/tiles 2>/dev/null || echo "sin caché todavía"
    fi ;;
  purge)
    if alive; then curl -s -X POST "http://127.0.0.1:$PORT/cache/purge" >/dev/null \
      && echo "caché vaciada";
    else rm -rf ../cache/tiles && echo "caché vaciada (servidor parado)"; fi ;;
  *) echo "uso: $0 start|stop|status|restart|cache|purge [puerto]"; exit 2 ;;
esac
