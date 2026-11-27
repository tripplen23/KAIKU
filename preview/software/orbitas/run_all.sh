#!/bin/sh
# Reproduce todos los resultados de D10/D11/D12 y de los tres encargos
# anadidos el 28-oct (umbral USML 0,50 m, radiador pasivo, cadencia, AoR Alto
# Norte). Solo stdlib de Python 3. Uso: sh run_all.sh  desde software/orbitas/
set -e
python3 orbitas_def.py   > resultados/00_catalogo.txt
for f in 01_geometria 02_cobertura 03_gsd 04_radiacion 05_enlace 06_acceso \
         07_carga_util 08_variantes 09_punto_diseno 10_alto_norte \
         11_termico 12_cadencia ; do
  python3 $f.py > /dev/null
  echo "  $f  ok"
done
echo "OK. Resultados en resultados/"
