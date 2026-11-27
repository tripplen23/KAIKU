# 09 — Ficha del punto de diseno recomendado

Generado por `09_punto_diseno.py`. Constelacion de 3 satelites espaciados T_rep/3 sobre la misma traza, con correccion de nodo. Estadistica del satelite servidor (el de mayor elevacion en cada instante) sobre 4 ciclos de repeticion, paso 30 s.


## BASELINE 12 h hp=4.500 km, N=3

a = 26562 km · e = 0.5905 · i = 63.435 deg · argp = 270 deg · T = 11.967 h · hp = 4500 km · ha = 35867 km · N = 3 satelites espaciados 7.98 h · L en cruce del ecuador magnetico = 2.71

| Sitio | el min [deg] | el mediana [deg] | escorzo peor caso | R mediana [km] | R p90 [km] | R max [km] |
|---|---|---|---|---|---|---|
| Mar de Barents central | 40.9 | 70.3 | 1.53 | 32721 | 35846 | 35976 |
| Aproximaciones a Kola / Varanger | 44.0 | 72.9 | 1.44 | 32643 | 35804 | 35935 |
| Mar de Noruega, rutas del Alto Norte | 45.5 | 73.8 | 1.40 | 32617 | 35801 | 35934 |
| Sur de Svalbard | 43.0 | 66.9 | 1.47 | 33566 | 36032 | 37624 |
| Estrecho de Fram / borde de hielo | 45.1 | 63.6 | 1.41 | 34407 | 37314 | 37431 |
| Golfo de Finlandia (referencia heredada) | 56.4 | 83.2 | 1.20 | 32443 | 35746 | 35883 |

Peor caso sobre TODO el AoR del Alto Norte: el_min = 40.9 deg, R p90 = 37314 km.

| Banda | GSD_eff objetivo [m] | apertura D [m] | bajo umbral USML 0,50 m | masa de carga [kg] (parametrico) |
|---|---|---|---|---|
| MWIR 4,0 um | 500 | 0.56 | **NO, controlado** | 57 - 111 |
| MWIR 4,0 um | 300 | 0.93 | **NO, controlado** | 150 - 343 |
| VIS 0,55 um | 50 | 0.76 | **NO, controlado** | 101 - 220 |
| MWIR 4,0 um | -> 927 (resultante) | 0.30 | si | 28 - 40 |
| VIS 0,55 um | -> 127 (resultante) | 0.30 | si | 28 - 40 |
| MWIR 4,0 um | -> 695 (resultante) | 0.40 | si | 37 - 60 |
| VIS 0,55 um | -> 96 (resultante) | 0.40 | si | 37 - 60 |
| MWIR 4,0 um | -> 556 (resultante) | 0.50 | si | 48 - 90 |
| VIS 0,55 um | -> 76 (resultante) | 0.50 | si | 48 - 90 |

## CRECIMIENTO 12 h hp=5.000 km, N=4

a = 26562 km · e = 0.5716 · i = 63.435 deg · argp = 270 deg · T = 11.967 h · hp = 5000 km · ha = 35367 km · N = 4 satelites espaciados 5.98 h · L en cruce del ecuador magnetico = 2.80

| Sitio | el min [deg] | el mediana [deg] | escorzo peor caso | R mediana [km] | R p90 [km] | R max [km] |
|---|---|---|---|---|---|---|
| Mar de Barents central | 58.2 | 73.3 | 1.18 | 33679 | 35404 | 35476 |
| Aproximaciones a Kola / Varanger | 61.1 | 75.9 | 1.14 | 33615 | 35362 | 35435 |
| Mar de Noruega, rutas del Alto Norte | 62.3 | 76.6 | 1.13 | 33601 | 35361 | 35435 |
| Sur de Svalbard | 54.8 | 69.9 | 1.22 | 33780 | 35482 | 35553 |
| Estrecho de Fram / borde de hielo | 51.6 | 66.6 | 1.28 | 33897 | 35579 | 35651 |
| Golfo de Finlandia (referencia heredada) | 72.8 | 84.4 | 1.05 | 33478 | 35306 | 35383 |

Peor caso sobre TODO el AoR del Alto Norte: el_min = 51.6 deg, R p90 = 35579 km.

| Banda | GSD_eff objetivo [m] | apertura D [m] | bajo umbral USML 0,50 m | masa de carga [kg] (parametrico) |
|---|---|---|---|---|
| MWIR 4,0 um | 500 | 0.44 | si | 41 - 72 |
| MWIR 4,0 um | 300 | 0.74 | **NO, controlado** | 94 - 204 |
| VIS 0,55 um | 50 | 0.61 | **NO, controlado** | 66 - 134 |
| MWIR 4,0 um | -> 738 (resultante) | 0.30 | si | 28 - 40 |
| VIS 0,55 um | -> 102 (resultante) | 0.30 | si | 28 - 40 |
| MWIR 4,0 um | -> 554 (resultante) | 0.40 | si | 37 - 60 |
| VIS 0,55 um | -> 76 (resultante) | 0.40 | si | 37 - 60 |
| MWIR 4,0 um | -> 443 (resultante) | 0.50 | si | 48 - 90 |
| VIS 0,55 um | -> 61 (resultante) | 0.50 | si | 48 - 90 |

## ALT-1 Molniya clasica hp=600 km

a = 26562 km · e = 0.7373 · i = 63.435 deg · argp = 270 deg · T = 11.967 h · hp = 600 km · ha = 39767 km · N = 3 satelites espaciados 7.98 h · L en cruce del ecuador magnetico = 1.90

| Sitio | el min [deg] | el mediana [deg] | escorzo peor caso | R mediana [km] | R p90 [km] | R max [km] |
|---|---|---|---|---|---|---|
| Mar de Barents central | 57.2 | 74.7 | 1.19 | 36324 | 39734 | 39875 |
| Aproximaciones a Kola / Varanger | 60.3 | 77.4 | 1.15 | 36263 | 39694 | 39835 |
| Mar de Noruega, rutas del Alto Norte | 61.8 | 78.1 | 1.13 | 36245 | 39691 | 39833 |
| Sur de Svalbard | 53.6 | 71.2 | 1.24 | 36422 | 39810 | 39950 |
| Estrecho de Fram / borde de hielo | 50.2 | 67.8 | 1.30 | 36535 | 39906 | 40046 |
| Golfo de Finlandia (referencia heredada) | 73.6 | 86.3 | 1.04 | 36131 | 39638 | 39782 |

Peor caso sobre TODO el AoR del Alto Norte: el_min = 50.2 deg, R p90 = 39906 km.

| Banda | GSD_eff objetivo [m] | apertura D [m] | bajo umbral USML 0,50 m | masa de carga [kg] (parametrico) |
|---|---|---|---|---|
| MWIR 4,0 um | 500 | 0.51 | **NO, controlado** | 49 - 92 |
| MWIR 4,0 um | 300 | 0.84 | **NO, controlado** | 123 - 276 |
| VIS 0,55 um | 50 | 0.70 | **NO, controlado** | 84 - 179 |
| MWIR 4,0 um | -> 844 (resultante) | 0.30 | si | 28 - 40 |
| VIS 0,55 um | -> 116 (resultante) | 0.30 | si | 28 - 40 |
| MWIR 4,0 um | -> 633 (resultante) | 0.40 | si | 37 - 60 |
| VIS 0,55 um | -> 87 (resultante) | 0.40 | si | 37 - 60 |
| MWIR 4,0 um | -> 507 (resultante) | 0.50 | si | 48 - 90 |
| VIS 0,55 um | -> 70 (resultante) | 0.50 | si | 48 - 90 |

## ALT-2 Tundra e=0,25

a = 42164 km · e = 0.2500 · i = 63.435 deg · argp = 270 deg · T = 23.934 h · hp = 25245 km · ha = 46327 km · N = 3 satelites espaciados 7.98 h · L en cruce del ecuador magnetico = 6.20

| Sitio | el min [deg] | el mediana [deg] | escorzo peor caso | R mediana [km] | R p90 [km] | R max [km] |
|---|---|---|---|---|---|---|
| Mar de Barents central | 56.8 | 72.3 | 1.19 | 45671 | 46400 | 46432 |
| Aproximaciones a Kola / Varanger | 59.8 | 74.9 | 1.16 | 45599 | 46360 | 46392 |
| Mar de Noruega, rutas del Alto Norte | 61.1 | 75.5 | 1.14 | 45579 | 46359 | 46393 |
| Sur de Svalbard | 53.4 | 68.9 | 1.25 | 45780 | 46477 | 46506 |
| Estrecho de Fram / borde de hielo | 50.3 | 65.7 | 1.30 | 45902 | 46572 | 46601 |
| Golfo de Finlandia (referencia heredada) | 71.9 | 85.1 | 1.05 | 45425 | 46304 | 46342 |

Peor caso sobre TODO el AoR del Alto Norte: el_min = 50.3 deg, R p90 = 46572 km.

| Banda | GSD_eff objetivo [m] | apertura D [m] | bajo umbral USML 0,50 m | masa de carga [kg] (parametrico) |
|---|---|---|---|---|
| MWIR 4,0 um | 500 | 0.59 | **NO, controlado** | 63 - 125 |
| MWIR 4,0 um | 300 | 0.98 | **NO, controlado** | 171 - 395 |
| VIS 0,55 um | 50 | 0.81 | **NO, controlado** | 113 - 252 |
| MWIR 4,0 um | -> 984 (resultante) | 0.30 | si | 28 - 40 |
| VIS 0,55 um | -> 135 (resultante) | 0.30 | si | 28 - 40 |
| MWIR 4,0 um | -> 738 (resultante) | 0.40 | si | 37 - 60 |
| VIS 0,55 um | -> 101 (resultante) | 0.40 | si | 37 - 60 |
| MWIR 4,0 um | -> 590 (resultante) | 0.50 | si | 48 - 90 |
| VIS 0,55 um | -> 81 (resultante) | 0.50 | si | 48 - 90 |
