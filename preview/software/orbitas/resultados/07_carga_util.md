# 07 — Dimensionado de la carga util por orbita  (D11)

Generado por `07_carga_util.py`. Modelo de masa parametrico; coeficientes declarados en la cabecera del script. Rango de masa = coeficiente de OTA entre 120 y 300 kg/m^2,5. Potencia fija: 80 W criogenerador + 35 W electronica + 60 W transmisor = 175 W [SUPUESTO].


## REQ-A  MWIR GSD_eff <= 500 m

| Orbita | D [m] | f [m] | F/# | masa carga [kg] | potencia [W] | long. tubo+parasol [m] | diametro envolv. [m] | volumen [m3] | veredicto |
|---|---|---|---|---|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 0.01 | 0.03 | 3.1 | 21 - 21 | 175 | 0.03 | 0.16 | 0.001 | carga hospedada en casi cualquier bus |
| LEO alta 2.000 km i=63.4 | 0.03 | 0.08 | 3.1 | 21 - 21 | 175 | 0.09 | 0.18 | 0.002 | carga hospedada en casi cualquier bus |
| MEO 8.000 km i=63.4 | 0.10 | 0.31 | 3.1 | 21 - 22 | 175 | 0.34 | 0.25 | 0.017 | carga hospedada en casi cualquier bus |
| MEO 20.000 km i=63.4 | 0.23 | 0.71 | 3.1 | 25 - 31 | 175 | 0.79 | 0.38 | 0.090 | carga hospedada en casi cualquier bus |
| GEO 35.786 km @25 E | 1.02 | 3.13 | 3.1 | 184 - 429 | 175 | 3.49 | 1.17 | 3.742 | **exige satelite propio** |
| Molniya 12 h, hp=600 km, i=63.4 | 0.40 | 1.24 | 3.1 | 37 - 61 | 175 | 1.38 | 0.55 | 0.332 | carga hospedada negociable en bus GEO/HEO grande |
| Tundra 24 h, e=0.25, i=63.4 | 0.48 | 1.46 | 3.1 | 45 - 82 | 175 | 1.63 | 0.63 | 0.500 | carga hospedada negociable en bus GEO/HEO grande |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 0.47 | 1.45 | 3.1 | 44 - 80 | 175 | 1.61 | 0.62 | 0.487 | carga hospedada negociable en bus GEO/HEO grande |

## REQ-B  VIS GSD_eff <= 50 m

| Orbita | D [m] | f [m] | F/# | masa carga [kg] | potencia [W] | long. tubo+parasol [m] | diametro envolv. [m] | volumen [m3] | veredicto |
|---|---|---|---|---|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 0.01 | 0.10 | 8.2 | 21 - 21 | 175 | 0.06 | 0.16 | 0.001 | carga hospedada en casi cualquier bus |
| LEO alta 2.000 km i=63.4 | 0.04 | 0.30 | 8.2 | 21 - 21 | 175 | 0.18 | 0.19 | 0.005 | carga hospedada en casi cualquier bus |
| MEO 8.000 km i=63.4 | 0.14 | 1.12 | 8.2 | 22 - 24 | 175 | 0.68 | 0.29 | 0.044 | carga hospedada en casi cualquier bus |
| MEO 20.000 km i=63.4 | 0.32 | 2.60 | 8.2 | 30 - 43 | 175 | 1.57 | 0.47 | 0.270 | carga hospedada negociable en bus GEO/HEO grande |
| GEO 35.786 km @25 E | 1.40 | 11.48 | 8.2 | 383 - 927 | 175 | 6.95 | 1.55 | 13.126 | **exige satelite propio** |
| Molniya 12 h, hp=600 km, i=63.4 | 0.55 | 4.54 | 8.2 | 57 - 110 | 175 | 2.75 | 0.70 | 1.072 | **exige satelite propio** |
| Tundra 24 h, e=0.25, i=63.4 | 0.65 | 5.36 | 8.2 | 75 - 156 | 175 | 3.24 | 0.80 | 1.645 | **exige satelite propio** |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 0.65 | 5.30 | 8.2 | 73 - 152 | 175 | 3.21 | 0.80 | 1.601 | **exige satelite propio** |

## REQ-C  MWIR <= 300 m

| Orbita | D [m] | f [m] | F/# | masa carga [kg] | potencia [W] | long. tubo+parasol [m] | diametro envolv. [m] | volumen [m3] | veredicto |
|---|---|---|---|---|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 0.02 | 0.05 | 3.1 | 21 - 21 | 175 | 0.05 | 0.17 | 0.001 | carga hospedada en casi cualquier bus |
| LEO alta 2.000 km i=63.4 | 0.04 | 0.14 | 3.1 | 21 - 21 | 175 | 0.15 | 0.19 | 0.005 | carga hospedada en casi cualquier bus |
| MEO 8.000 km i=63.4 | 0.17 | 0.51 | 3.1 | 23 - 25 | 175 | 0.57 | 0.32 | 0.045 | carga hospedada en casi cualquier bus |
| MEO 20.000 km i=63.4 | 0.38 | 1.18 | 3.1 | 35 - 57 | 175 | 1.32 | 0.53 | 0.296 | carga hospedada negociable en bus GEO/HEO grande |
| GEO 35.786 km @25 E | 1.70 | 5.22 | 3.1 | 607 - 1486 | 175 | 5.81 | 1.85 | 15.591 | **exige satelite propio** |
| Molniya 12 h, hp=600 km, i=63.4 | 0.67 | 2.07 | 3.1 | 79 - 165 | 175 | 2.30 | 0.82 | 1.221 | **exige satelite propio** |
| Tundra 24 h, e=0.25, i=63.4 | 0.79 | 2.44 | 3.1 | 108 - 239 | 175 | 2.71 | 0.94 | 1.892 | **exige satelite propio** |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 0.78 | 2.41 | 3.1 | 106 - 233 | 175 | 2.68 | 0.93 | 1.840 | **exige satelite propio** |

## Lectura

1. **El dimensionado de la carga lo fija la distancia, no la orbita.** Entre
   Molniya y Tundra hay un 16,8% de diferencia de distancia de diseno (39.638
   frente a 46.304 km, p90 del satelite servidor). Con la elevacion minima de
   cada una, la apertura necesaria sube un 17,9% y la masa de OTA, con
   exponente 2,5, un **51%** para Tundra a igual requisito. Ese es el precio
   exacto de la ventaja de radiacion de Tundra. [CALCULADO]
2. **Desde LEO, el instrumento es trivial y no hay producto.** Una apertura de
   1-4 cm cumple cualquiera de los tres requisitos. Eso confirma que en LEO la
   barrera de entrada no es optica, es constelacion: 576 satelites para
   persistencia (ver `02_cobertura.md`). No es nuestro juego.
3. **El criogenerador y su potencia, no la optica, son lo que te echa de una
   carga hospedada pequena.** 175 W continuos es mucho para un hueco de
   oportunidad. Un bus de telecomunicaciones de clase GEO/HEO (varios kW) lo
   absorbe sin problema; un microsatelite de 100 kg, no.
4. **El parasol, no el tubo, domina la envolvente** en las aperturas pequenas.
   Un instrumento que mira a la Tierra desde el apogeo con el Sol cerca del
   campo necesita rechazo de luz parasita; es el componente que mas crece si se
   quiere operar tambien en verano artico con el Sol a 24 h.

