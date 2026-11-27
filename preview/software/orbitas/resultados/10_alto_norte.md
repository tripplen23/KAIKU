# 10 — Cobertura contra el area de responsabilidad del Alto Norte

AoR: Barents central 73 N 30 E · Kola/Varanger 70 N 35 E · Mar de Noruega 68 N 10 E · Svalbard sur 76 N 18 E · Fram 78 N 5 E. El Golfo de Finlandia se mantiene solo como referencia heredada (GOFREP ya lo cubre desde tierra).

Criterio exigente: **todos** los sitios del AoR vistos simultaneamente por al menos un satelite. Paso 60 s, 3 ciclos de repeticion.


## Las ocho orbitas frente al AoR del Alto Norte

| Orbita | %t 1 sat ve TODO el AoR a el>20 | idem a el>40 | N para el>40 en todo el AoR | N para el>50 | R p90 [km] | el_min [deg] | D MWIR @500 m [m] | GSD_eff MWIR con D=0,50 m [m] |
|---|---|---|---|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 0.6 | 0.0 | n/a | n/a | - | - | - | - |
| LEO alta 2.000 km i=63.4 | 3.0 | 0.0 | n/a | n/a | - | - | - | - |
| MEO 8.000 km i=63.4 | 13.9 | 5.5 | n/a | n/a | - | - | - | - |
| MEO 20.000 km i=63.4 | 25.5 | 9.8 | n/a | n/a | - | - | - | - |
| GEO 35.786 km @25 E | 0.0 | 0.0 | >8 | >8 | - | - | - | - |
| Molniya 12 h, hp=600 km, i=63.4 | 71.1 | 37.3 | 3 | 3 | 39757 | 50.3 | 0.50 **>USML** | 505 |
| Tundra 24 h, e=0.25, i=63.4 | 54.9 | 41.6 | 3 | 3 | 46416 | 50.3 | 0.59 **>USML** | 588 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 59.9 | 32.4 | 4 | 6 | 43964 | 40.3 | 0.66 **>USML** | 663 |

## Barrido de inclinacion, familia 12 h con hp=5.000 km (a=26562 km, e=0.5716, ha=35367 km)

`N AoR+GoF` exige ver ademas el Golfo de Finlandia. La ultima columna es la deriva secular J2 del argumento del perigeo: a i=63,435 es nula por construccion; fuera de ahi hay que mantenerla o aceptar que el apogeo migra en latitud. [CALCULADO]

| i [deg] | N (el>40, AoR) | N (el>50, AoR) | N (el>40, AoR+GoF) | R p90 [km] | el_min [deg] | D MWIR @500 m [m] | GSD_eff con D=0,50 m [m] | deriva argp [deg/ano] |
|---|---|---|---|---|---|---|---|---|
| 63.435 | 4 | 4 | 4 | 35419 | 51.7 | 0.44 | 441 | -0.00 |
| 66.000 | 3 | 4 | 3 | 35422 | 42.4 | 0.51 | 513 | -4.71 |
| 68.000 | 3 | 4 | 3 | 35405 | 42.9 | 0.51 | 508 | -8.13 |
| 70.000 | 3 | 4 | 3 | 35406 | 43.8 | 0.50 | 499 | -11.31 |
| 72.000 | 3 | 4 | 3 | 35427 | 45.0 | 0.49 | 489 | -14.23 |
| 75.000 | 3 | 4 | 3 | 35936 | 47.1 | 0.48 | 479 | -18.12 |
| 80.000 | 3 | 3 | 3 | 35875 | 51.6 | 0.45 | 447 | -23.13 |

## Perigeo x inclinacion, familia 12 h, frente al AoR del Alto Norte (el>40 en todos los sitios)

| hp [km] | i [deg] | ha [km] | N | R p90 [km] | el_min [deg] | D MWIR @500 m [m] | GSD_eff con D=0,50 m [m] | L en cruce ecuatorial |
|---|---|---|---|---|---|---|---|---|
| 600 | 63.435 | 39767 | 3 | 39757 | 50.3 | 0.50 | 505 | 1.90 |
| 600 | 70.000 | 39767 | 3 | 39667 | 54.0 | 0.48 | 479 | 1.90 |
| 2500 | 63.435 | 37867 | 3 | 37882 | 46.1 | 0.51 | 513 | 2.32 |
| 2500 | 70.000 | 37867 | 3 | 37826 | 50.8 | 0.48 | 476 | 2.32 |
| 5000 | 63.435 | 35367 | 4 | 35419 | 51.7 | 0.44 | 441 | 2.80 |
| 5000 | 70.000 | 35367 | 3 | 35406 | 43.8 | 0.50 | 499 | 2.80 |
| 8000 | 63.435 | 32367 | 4 | 32428 | 42.5 | 0.47 | 469 | 3.29 |
| 8000 | 70.000 | 32367 | 4 | 32345 | 44.8 | 0.45 | 448 | 3.29 |
| 11000 | 63.435 | 29367 | 5 | 29467 | 44.4 | 0.41 | 411 | 3.67 |
| 11000 | 70.000 | 29367 | 5 | 29384 | 49.3 | 0.38 | 378 | 3.67 |
