#!/usr/bin/env bash
# El entorno de Python del proyecto. Se corre a mano, cuando hace falta:
#
#   ./venv.sh            crea o actualiza el entorno con requirements.txt
#   ./venv.sh dev        además, lo de los tests (requirements-dev.txt)
#   ./venv.sh where      dice dónde está y qué tiene dentro
#   ./venv.sh rm         lo borra (es regenerable, no hay nada que perder)
#
# NO vive dentro del repo: son binarios compilados para esta máquina, pesan, y
# el repo está en Dropbox, que está lleno. Vive donde dice rutas.toml, junto al
# resto de lo regenerable. Lo que se copia a otra máquina es requirements.txt.
#
# Nada de esto se instala en el sistema ni se queda corriendo.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"          # el que lleva rutas.py
VENV="$(cd "$REPO" && python3 -c 'import rutas; print(rutas.venv())')"
PY="$VENV/bin/python3"

case "${1:-install}" in
  where)
    echo "$VENV"
    [ -x "$PY" ] || { echo "(no existe todavía: ./venv.sh)"; exit 1; }
    echo; "$PY" -m pip list --format=columns
    echo; echo "tamaño: $(du -sh "$VENV" | cut -f1)"
    ;;
  rm)
    [ -d "$VENV" ] || { echo "no hay nada en $VENV"; exit 0; }
    rm -rf "$VENV"; echo "borrado $VENV"
    ;;
  install|dev)
    REQ="$HERE/requirements.txt"
    [ "${1:-install}" = dev ] && REQ="$HERE/requirements-dev.txt"
    if [ ! -x "$PY" ]; then
      echo "creando el entorno en $VENV"
      mkdir -p "$(dirname "$VENV")"
      python3 -m venv "$VENV"
    else
      echo "actualizando el entorno de $VENV"
    fi
    "$PY" -m pip install --quiet --upgrade pip
    "$PY" -m pip install -r "$REQ"
    echo
    echo "listo:   $VENV"
    echo "receta:  $REQ"
    echo "usarlo:  ./custody.sh build   (lo encuentra solo)"
    echo "         $PY  cualquier_script.py"
    ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
