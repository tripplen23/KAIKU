# 02 — Cobertura temporal  (D10.2)

Generado por `02_cobertura.py`. Paso 30 s. Ventana: 8 dias (traza repetida) / 14 dias (LEO-MEO).

Ciclos de repeticion de traza usados: Molniya 2 rev/1 dia, TAP 3 rev/2 dias, Tundra y GEO 1 rev/1 dia. [CALCULADO]


## GoF — Golfo de Finlandia, centro (59-61 N)

| Orbita | %t el>20 | %t el>40 | %t el>60 | accesos/dia | dur. media acc>40 [h] | hueco max [h] | el media (>40) [deg] | dist media (>40) [km] | dist media (>60) [km] | cota N>=1/f (el>40) |
|---|---|---|---|---|---|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 1.20 | 0.31 | 0.08 | 1.9 | 0.04 | 24.1 | 54 | 750 | 643 | 328 |
| LEO alta 2.000 km i=63.4 | 6.25 | 2.88 | 1.17 | 4.4 | 0.16 | 16.6 | 58 | 2314 | 2100 | 35 |
| MEO 8.000 km i=63.4 | 16.55 | 9.07 | 3.83 | 3.1 | 0.71 | 13.1 | 58 | 8666 | 8219 | 12 |
| MEO 20.000 km i=63.4 | 26.80 | 12.99 | 6.82 | 1.1 | 2.91 | 21.3 | 61 | 20724 | 20302 | 8 |
| GEO 35.786 km @25 E | 100.00 | 0.00 | 0.00 | 0.0 | 0.00 | 192.0 | - | - | - | n/a |
| Molniya 12 h, hp=600 km, i=63.4 | 64.24 | 42.26 | 38.42 | 1.0 | 10.14 | 13.8 | 80 | 31460 | 32983 | 3 |
| Tundra 24 h, e=0.25, i=63.4 | 64.36 | 54.33 | 42.33 | 1.0 | 13.04 | 10.9 | 73 | 43523 | 44506 | 2 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 59.38 | 24.60 | 20.95 | 0.5 | 11.81 | 36.1 | 76 | 36813 | 38624 | 5 |

## Utsjoki — Utsjoki, frontera norte

| Orbita | %t el>20 | %t el>40 | %t el>60 | accesos/dia | dur. media acc>40 [h] | hueco max [h] | el media (>40) [deg] | dist media (>40) [km] | dist media (>60) [km] | cota N>=1/f (el>40) |
|---|---|---|---|---|---|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 1.96 | 0.49 | 0.11 | 3.1 | 0.04 | 14.7 | 53 | 754 | 643 | 206 |
| LEO alta 2.000 km i=63.4 | 5.40 | 1.83 | 0.20 | 3.4 | 0.13 | 18.8 | 50 | 2435 | 2193 | 55 |
| MEO 8.000 km i=63.4 | 18.00 | 8.34 | 2.81 | 3.1 | 0.65 | 13.3 | 55 | 8751 | 8291 | 12 |
| MEO 20.000 km i=63.4 | 28.72 | 13.17 | 5.86 | 1.4 | 2.33 | 21.1 | 58 | 20859 | 20371 | 8 |
| GEO 35.786 km @25 E | 0.00 | 0.00 | 0.00 | 0.0 | 0.00 | 192.0 | - | - | - | n/a |
| Molniya 12 h, hp=600 km, i=63.4 | 73.60 | 40.10 | 33.78 | 1.0 | 9.62 | 14.3 | 72 | 32558 | 34755 | 3 |
| Tundra 24 h, e=0.25, i=63.4 | 59.69 | 48.21 | 33.59 | 1.0 | 11.57 | 12.4 | 67 | 44351 | 45326 | 3 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 63.93 | 41.54 | 17.72 | 1.5 | 6.65 | 11.8 | 59 | 40847 | 40167 | 3 |

## Constelacion de traza repetida: N minimo para 24/7

N satelites espaciados T_rep/N con correccion de nodo -omega_e*dt. Verificado sobre 4 ciclos completos, paso 60 s. `el_min` y `R(el_min)` son el peor instante del ciclo: ese es el punto de diseno de apertura y enlace, no el apogeo.


### Golfo de Finlandia, centro (59-61 N)

| Orbita | N (el>40) | N (el>60) | N (el>70) | con N(el>60): elevacion minima y distancia del satelite servidor [km] |
|---|---|---|---|---|
| GEO 35.786 km @25 E | >8 | >8 | >8 | - |
| Molniya 12 h, hp=600 km, i=63.4 | 3 | 3 | 3 | el_min=73.6 deg · R med=34774 · R p90=39638 · R max=39782 |
| Tundra 24 h, e=0.25, i=63.4 | 2 | 3 | 3 | el_min=71.9 deg · R med=45163 · R p90=46304 · R max=46342 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 5 | 5 | 6 | el_min=64.2 deg · R med=39081 · R p90=43397 · R max=43530 |

### Utsjoki, frontera norte

| Orbita | N (el>40) | N (el>60) | N (el>70) | con N(el>60): elevacion minima y distancia del satelite servidor [km] |
|---|---|---|---|---|
| GEO 35.786 km @25 E | >8 | >8 | >8 | - |
| Molniya 12 h, hp=600 km, i=63.4 | 3 | 3 | 4 | el_min=61.1 deg · R med=34922 · R p90=39674 · R max=39816 |
| Tundra 24 h, e=0.25, i=63.4 | 3 | 3 | 5 | el_min=60.4 deg · R med=45346 · R p90=46341 · R max=46374 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 4 | 6 | 8 | el_min=63.2 deg · R med=40569 · R p90=43439 · R max=43528 |

## Constelacion Walker-delta: total minimo para cobertura continua del Golfo de Finlandia

Rejilla P en {2,3,4,5,6,8,10,12,15,18,21,24,28} x S en {1..24}, 1 dia sidereo, paso 60 s, techo 900 satelites. Es el minimo SOBRE LA REJILLA, no un optimo global: un diseno dedicado puede bajarlo ~20-30%. El orden de magnitud es el resultado.

| Orbita | Total min. el>40 | Total min. el>60 |
|---|---|---|
| LEO SSO 600 km (i=97.79) | 576 (P=24 x S=24) | >900 |
| LEO alta 2.000 km i=63.4 | 42 (P=3 x S=14) | 108 (P=18 x S=6) |
| MEO 8.000 km i=63.4 | 16 (P=8 x S=2) | 32 (P=8 x S=4) |
| MEO 20.000 km i=63.4 | 10 (P=2 x S=5) | 24 (P=3 x S=8) |
