# 03 — GSD limitada por difraccion  (D10.3)

Generado por `03_gsd.py`. theta = 1,22 lambda/D. GSD_eff = theta*R/sin(el). Sin considerar MTF del detector, jitter, ni atmosfera: es el techo fisico, no el rendimiento alcanzable. Un sistema real entrega entre 1,3x y 2x peor. [SUPUESTO ACOTADO]


## Puntos de operacion usados

| Orbita | R diseno [km] | elevacion [deg] | escorzo 1/sin(el) | criterio |
|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 750 | 53.7 | 1.24 | media durante accesos el>40 |
| LEO alta 2.000 km i=63.4 | 2314 | 57.9 | 1.18 | media durante accesos el>40 |
| MEO 8.000 km i=63.4 | 8666 | 58.1 | 1.18 | media durante accesos el>40 |
| MEO 20.000 km i=63.4 | 20724 | 61.2 | 1.14 | media durante accesos el>40 |
| GEO 35.786 km @25 E | 39344 | 22.1 | 2.65 | estatico sobre el Golfo (slot 25 E) |
| Molniya 12 h, hp=600 km, i=63.4 | 39638 | 73.6 | 1.04 | p90 del servidor, constelacion N=3 (el>60) |
| Tundra 24 h, e=0.25, i=63.4 | 46304 | 71.9 | 1.05 | p90 del servidor, constelacion N=3 (el>60) |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 43397 | 64.2 | 1.11 | p90 del servidor, constelacion N=5 (el>60) |

## GSD efectiva [m] — MWIR 4,0 um (direccion de maximo escorzo)

| Orbita | D=0.2 m | D=0.3 m | D=0.5 m | D=1.0 m |
|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 22.7 | 15.1 | 9.1 | 4.5 |
| LEO alta 2.000 km i=63.4 | 66.7 | 44.4 | 26.7 | 13.3 |
| MEO 8.000 km i=63.4 | 249 | 166 | 99.6 | 49.8 |
| MEO 20.000 km i=63.4 | 577 | 385 | 231 | 115 |
| GEO 35.786 km @25 E | 2547 | 1698 | 1019 | 509 |
| Molniya 12 h, hp=600 km, i=63.4 | 1008 | 672 | 403 | 202 |
| Tundra 24 h, e=0.25, i=63.4 | 1189 | 792 | 475 | 238 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 1176 | 784 | 471 | 235 |

## GSD efectiva [m] — VIS 0,55 um (direccion de maximo escorzo)

| Orbita | D=0.2 m | D=0.3 m | D=0.5 m | D=1.0 m |
|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 3.1 | 2.1 | 1.2 | 0.6 |
| LEO alta 2.000 km i=63.4 | 9.2 | 6.1 | 3.7 | 1.8 |
| MEO 8.000 km i=63.4 | 34.3 | 22.8 | 13.7 | 6.9 |
| MEO 20.000 km i=63.4 | 79.4 | 52.9 | 31.7 | 15.9 |
| GEO 35.786 km @25 E | 350 | 234 | 140 | 70.1 |
| Molniya 12 h, hp=600 km, i=63.4 | 139 | 92.4 | 55.4 | 27.7 |
| Tundra 24 h, e=0.25, i=63.4 | 163 | 109 | 65.4 | 32.7 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 162 | 108 | 64.7 | 32.4 |

## Apertura requerida [m] para una GSD efectiva objetivo

| Orbita | MWIR @500 m | MWIR @300 m | MWIR @100 m | VIS @50 m | VIS @20 m |
|---|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 0.01 | 0.02 | 0.05 | 0.01 | 0.03 |
| LEO alta 2.000 km i=63.4 | 0.03 | 0.04 | 0.13 | 0.04 | 0.09 |
| MEO 8.000 km i=63.4 | 0.10 | 0.17 | 0.50 | 0.14 | 0.34 |
| MEO 20.000 km i=63.4 | 0.23 | 0.38 | 1.15 | 0.32 | 0.79 |
| GEO 35.786 km @25 E | 1.02 | 1.70 | 5.09 | 1.40 | 3.50 |
| Molniya 12 h, hp=600 km, i=63.4 | 0.40 | 0.67 | 2.02 | 0.55 | 1.39 |
| Tundra 24 h, e=0.25, i=63.4 | 0.48 | 0.79 | 2.38 | 0.65 | 1.63 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 0.47 | 0.78 | 2.35 | 0.65 | 1.62 |

**Linea roja de cumplimiento: 0,50 m.** USML XV(e)(2) situa el umbral de control en 0,50 m de apertura (fuente: Compliance & Legal, `canal/iteracion_01/06_compliance_legal.md`). Toda celda por encima de 0,50 m saca la carga de la regla D12 de cadena de suministro europea. Las aperturas del encargo (0,2 / 0,3 / 0,5 m) estan dentro; 1,0 m no.


## GSD efectiva alcanzable con D = 0,50 m exactos (apertura maxima sin control USML XV(e)(2))

| Orbita | R diseno [km] | el [deg] | GSD_eff MWIR [m] | GSD_eff VIS [m] |
|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 750 | 53.7 | 9 | 1 |
| LEO alta 2.000 km i=63.4 | 2314 | 57.9 | 27 | 4 |
| MEO 8.000 km i=63.4 | 8666 | 58.1 | 100 | 14 |
| MEO 20.000 km i=63.4 | 20724 | 61.2 | 231 | 32 |
| GEO 35.786 km @25 E | 39344 | 22.1 | 1019 | 140 |
| Molniya 12 h, hp=600 km, i=63.4 | 39638 | 73.6 | 403 | 55 |
| Tundra 24 h, e=0.25, i=63.4 | 46304 | 71.9 | 475 | 65 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 43397 | 64.2 | 471 | 65 |

## Distancia focal, F/# y longitud de tubo (Nyquist: 1 px = GSD)

Paso de pixel supuesto: MWIR 15 um, VIS 5,5 um [SUPUESTO, pasos comerciales]. f = pitch * R / GSD_nadir. Longitud de tubo estimada como 0,30*f para un Cassegrain plegado (factor tipico 0,25-0,35) [SUPUESTO].

| Orbita | Banda | GSD_eff obj [m] | D [m] | f [m] | F/# | tubo ~0,3f [m] |
|---|---|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | MWIR 4,0 um | 500 | 0.01 | 0.03 | 3.1 | 0.01 |
| LEO SSO 600 km (i=97.79) | VIS 0,55 um | 50 | 0.01 | 0.10 | 8.2 | 0.03 |
| LEO alta 2.000 km i=63.4 | MWIR 4,0 um | 500 | 0.03 | 0.08 | 3.1 | 0.02 |
| LEO alta 2.000 km i=63.4 | VIS 0,55 um | 50 | 0.04 | 0.30 | 8.2 | 0.09 |
| MEO 8.000 km i=63.4 | MWIR 4,0 um | 500 | 0.10 | 0.31 | 3.1 | 0.09 |
| MEO 8.000 km i=63.4 | VIS 0,55 um | 50 | 0.14 | 1.12 | 8.2 | 0.34 |
| MEO 20.000 km i=63.4 | MWIR 4,0 um | 500 | 0.23 | 0.71 | 3.1 | 0.21 |
| MEO 20.000 km i=63.4 | VIS 0,55 um | 50 | 0.32 | 2.60 | 8.2 | 0.78 |
| GEO 35.786 km @25 E | MWIR 4,0 um | 500 | 1.02 | 3.13 | 3.1 | 0.94 |
| GEO 35.786 km @25 E | VIS 0,55 um | 50 | 1.40 | 11.48 | 8.2 | 3.45 |
| Molniya 12 h, hp=600 km, i=63.4 | MWIR 4,0 um | 500 | 0.40 | 1.24 | 3.1 | 0.37 |
| Molniya 12 h, hp=600 km, i=63.4 | VIS 0,55 um | 50 | 0.55 | 4.54 | 8.2 | 1.36 |
| Tundra 24 h, e=0.25, i=63.4 | MWIR 4,0 um | 500 | 0.48 | 1.46 | 3.1 | 0.44 |
| Tundra 24 h, e=0.25, i=63.4 | VIS 0,55 um | 50 | 0.65 | 5.36 | 8.2 | 1.61 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | MWIR 4,0 um | 500 | 0.47 | 1.45 | 3.1 | 0.43 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | VIS 0,55 um | 50 | 0.65 | 5.30 | 8.2 | 1.59 |
