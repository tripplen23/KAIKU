# 08 — Barrido de variantes dentro de cada familia  (D10)

Generado por `08_variantes.py`. Sitio: Golfo de Finlandia 59,80 N 25,50 E. `N` = satelites para elevacion >60 deg el 100% del tiempo. `D MWIR` = apertura para GSD_eff 500 m a la distancia p90. `L_eq` = L en el cruce del ecuador magnetico (dominante para el dano por desplazamiento en el FPA). `dV GTO` desde GTO Kourou i=6.

| Variante | hp [km] | ha [km] | e | N (el>60) | R p90 servidor [km] | el_min [deg] | D MWIR @500 m [m] | L_eq | h/dia en L1,2-2,5 | dV GTO [m/s] | lat. cruce anillo GEO [deg] |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Molniya 12 h hp=600 km | 600 | 39767 | 0.7373 | 3 | 39638 | 73.6 | 0.40 | 1.90 | 2.15 | 1916 | 59.8 |
| Molniya 12 h hp=1500 km | 1500 | 38867 | 0.7034 | 3 | 38739 | 70.2 | 0.40 | 2.10 | 2.10 | 1899 | 60.1 |
| Molniya 12 h hp=3000 km | 3000 | 37367 | 0.6469 | 3 | 37242 | 63.7 | 0.41 | 2.42 | 1.76 | 1852 | 61.2 |
| Molniya 12 h hp=5000 km | 5000 | 35367 | 0.5716 | 4 | 35306 | 72.8 | 0.36 | 2.80 | 0.00 | 1792 | no cruza |
| Molniya 12 h hp=8000 km | 8000 | 32367 | 0.4587 | 4 | 32313 | 62.0 | 0.36 | 3.29 | 0.00 | 2103 | no cruza |
| Molniya 12 h hp=10000 km | 10000 | 30367 | 0.3834 | 5 | 30344 | 64.6 | 0.33 | 3.55 | 0.00 | 2322 | no cruza |
| Molniya 12 h hp=12000 km | 12000 | 28367 | 0.3081 | 6 | 28361 | 64.5 | 0.31 | 3.77 | 0.00 | 2553 | no cruza |
| Tundra 24 h e=0.15 | 29461 | 42111 | 0.1500 | 3 | 42100 | 64.3 | 0.46 | 6.46 | 0.00 | 3109 | 7.7 |
| Tundra 24 h e=0.20 | 27353 | 44219 | 0.2000 | 3 | 44202 | 68.3 | 0.46 | 6.35 | 0.00 | 3173 | 10.3 |
| Tundra 24 h e=0.25 | 25245 | 46327 | 0.2500 | 3 | 46304 | 71.9 | 0.48 | 6.20 | 0.00 | 3218 | 12.9 |
| Tundra 24 h e=0.30 | 23137 | 48435 | 0.3000 | 3 | 48408 | 74.9 | 0.49 | 6.02 | 0.00 | 3247 | 15.6 |
| Tundra 24 h e=0.35 | 21029 | 50543 | 0.3500 | 3 | 50512 | 77.2 | 0.51 | 5.80 | 0.00 | 3264 | 18.2 |
| TAP 16 h hp=8100 km | 8100 | 43498 | 0.5501 | 5 | 43395 | 64.2 | 0.47 | 3.52 | 0.00 | 2580 | 50.4 |
| TAP 16 h hp=11000 km | 11000 | 40598 | 0.4599 | 6 | 40542 | 67.7 | 0.43 | 3.98 | 0.00 | 2527 | 51.7 |
| TAP 16 h hp=14000 km | 14000 | 37598 | 0.3667 | 7 | 37572 | 66.7 | 0.40 | 4.37 | 0.00 | 2394 | 57.0 |

## Barrido fino del perigeo en la familia Molniya 12 h

R en km, el en grados, D = apertura MWIR para GSD_eff 500 m en metros. El salto de N=3 a N=4 entre hp=3.750 y hp=4.000 km para el>60 es el compromiso central de esta familia.

| hp [km] | e | ha [km] | el>50 | el>60 | el>70 | L_eq | h/dia L1,2-2,5 | dV GTO [m/s] | lat. anillo GEO |
|---|---|---|---|---|---|---|---|---|---|
| 2500 | 0.6658 | 37867 | N=3 R=37741 el=66 D=0.40 | N=3 R=37741 el=66 D=0.40 | N=4 R=37803 el=80 D=0.37 | 2.32 | 1.91 | 1871 | 60.7 |
| 2750 | 0.6563 | 37617 | N=3 R=37491 el=65 D=0.40 | N=3 R=37491 el=65 D=0.40 | N=4 R=37553 el=80 D=0.37 | 2.37 | 1.84 | 1862 | 60.9 |
| 3000 | 0.6469 | 37367 | N=3 R=37242 el=64 D=0.41 | N=3 R=37242 el=64 D=0.41 | N=4 R=37303 el=79 D=0.37 | 2.42 | 1.76 | 1852 | 61.2 |
| 3250 | 0.6375 | 37117 | N=3 R=36992 el=63 D=0.41 | N=3 R=36992 el=63 D=0.41 | N=4 R=37053 el=78 D=0.37 | 2.47 | 1.65 | 1841 | 61.4 |
| 3500 | 0.6281 | 36867 | N=3 R=36743 el=61 D=0.41 | N=3 R=36743 el=61 D=0.41 | N=4 R=36804 el=78 D=0.37 | 2.52 | 1.53 | 1828 | 61.7 |
| 3750 | 0.6187 | 36617 | N=3 R=36493 el=60 D=0.41 | N=3 R=36493 el=60 D=0.41 | N=4 R=36554 el=77 D=0.37 | 2.57 | 1.37 | 1814 | 62.1 |
| 4000 | 0.6093 | 36367 | N=3 R=36244 el=59 D=0.41 | N=4 R=36304 el=76 D=0.37 | N=4 R=36304 el=76 D=0.37 | 2.62 | 1.18 | 1798 | 62.4 |
| 4250 | 0.5999 | 36117 | N=3 R=35995 el=58 D=0.42 | N=4 R=36055 el=75 D=0.36 | N=4 R=36055 el=75 D=0.36 | 2.67 | 0.92 | 1779 | 62.8 |
| 4500 | 0.5905 | 35867 | N=3 R=35746 el=56 D=0.42 | N=4 R=35805 el=74 D=0.36 | N=4 R=35805 el=74 D=0.36 | 2.71 | 0.48 | 1758 | 63.3 |
| 4750 | 0.5810 | 35617 | N=3 R=35496 el=55 D=0.42 | N=4 R=35555 el=74 D=0.36 | N=4 R=35555 el=74 D=0.36 | 2.76 | 0.00 | 1767 | no cruza |
| 5000 | 0.5716 | 35367 | N=3 R=35247 el=54 D=0.43 | N=4 R=35306 el=73 D=0.36 | N=4 R=35306 el=73 D=0.36 | 2.80 | 0.00 | 1792 | no cruza |
| 5250 | 0.5622 | 35117 | N=3 R=34998 el=53 D=0.43 | N=4 R=35056 el=72 D=0.36 | N=4 R=35056 el=72 D=0.36 | 2.85 | 0.00 | 1817 | no cruza |
| 5500 | 0.5528 | 34867 | N=3 R=34749 el=51 D=0.43 | N=4 R=34807 el=71 D=0.36 | N=4 R=34807 el=71 D=0.36 | 2.89 | 0.00 | 1842 | no cruza |
| 5750 | 0.5434 | 34617 | N=4 R=34558 el=70 D=0.36 | N=4 R=34558 el=70 D=0.36 | N=4 R=34558 el=70 D=0.36 | 2.93 | 0.00 | 1868 | no cruza |
| 6000 | 0.5340 | 34367 | N=4 R=34308 el=69 D=0.36 | N=4 R=34308 el=69 D=0.36 | N=5 R=34335 el=77 D=0.34 | 2.98 | 0.00 | 1893 | no cruza |

## Como se lee esta tabla

El parametro de diseno libre en la familia Molniya es el perigeo. Subirlo saca
el cruce del ecuador magnetico del cinturon de protones (L_eq pasa de 1,90 a
>3) y baja el apogeo, lo que mejora la distancia de diseno; el precio es que
el perigeo alto encarece el dV desde GTO y acorta la permanencia util.

Si existe una variante con L_eq > 3,0, h/dia en L1,2-2,5 = 0, N = 3 y
R p90 < 42.000 km, esa variante domina simultaneamente a Molniya clasica y a
Tundra, y no esta en la lista de seis orbitas del encargo. Es un punto de
diseno, no una familia de libro.

