#!/usr/bin/env bash
# Parada limpia del grabador AIS (REST y MQTT).
# Envía SIGTERM, espera a que el ciclo en curso cierre y haga fsync, y verifica el almacén.
# Uso: ./stop.sh [segundos_de_espera]   (por defecto 90)
set -u
cd "$(dirname "$0")"
WAIT="${1:-90}"
RC=0

for PAT in 'recorder' 'mqtt_ingest'; do
  PIDS=$(pgrep -af "${PAT}\.py" 2>/dev/null | grep -v -e '/bin/bash' -e pgrep \
         | awk '{print $1}' || true)
  [ -z "$PIDS" ] && { echo "· $PAT: no está corriendo"; continue; }
  echo "· $PAT: SIGTERM a $PIDS, esperando hasta ${WAIT}s"
  kill -TERM $PIDS 2>/dev/null
  for i in $(seq "$WAIT"); do
    pgrep -af "${PAT}\.py" 2>/dev/null | grep -qv -e /bin/bash -e pgrep || break
    sleep 1
  done
  if pgrep -af "${PAT}\.py" 2>/dev/null | grep -qv -e /bin/bash -e pgrep; then
    echo "  AVISO: sigue vivo tras ${WAIT}s. NO envío SIGKILL: hazlo tú si estás seguro."
    echo "         kill -9 \$(pgrep -af '${PAT}.py' | grep -v /bin/bash | awk '{print \$1}')"
    RC=1
  else
    echo "  parado limpiamente"
  fi
done

echo
echo "--- verificación del almacén ---"
python3 aisctl.py verify  || RC=1
echo
echo "--- resumen ---"
python3 aisctl.py summary || true
exit $RC
