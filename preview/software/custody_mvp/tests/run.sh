#!/usr/bin/env bash
# Toda la bateria, en un comando. Devuelve 0 si todo pasa.
#
# Tres niveles, de mas rapido a mas lento, y se paran en el primero que falla
# porque un fallo abajo hace ruido en todo lo de arriba:
#
#   1. unitarios de indicadores   python, sin red, sin build
#   2. licencias                  que nada sin permiso comercial este dentro
#   3. tiempo real                ventana, cobertura, cadencia y caducidad
#   4. humo del visor             carga el build real y pinta todo
set -u
cd "$(dirname "$0")/.."
fail=0
run () { printf '\n\033[1m== %s ==\033[0m\n' "$1"; shift; "$@" || fail=1; }

run "unitarios de indicadores" python3 tests/test_indicators.py
run "licencias"                python3 tests/test_licences.py
run "tiempo real"              python3 tests/test_runtime.py
run "humo del visor"           node tests/smoke.js

printf '\n'
if [ $fail -eq 0 ]; then printf '\033[32mTODO VERDE\033[0m\n'; else printf '\033[31mHAY FALLOS\033[0m\n'; fi
exit $fail
