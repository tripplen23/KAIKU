# 05 — Presupuesto de enlace de bajada  (D10.5)

Generado por `05_enlace.py`. Distancia de diseno = la misma que en `03_gsd.py` (p90 del satelite servidor para HEO, media de acceso para LEO/MEO). Eb/N0 requerido 2.5 dB + margen 3.0 dB.


## Contacto con una unica estacion en Sodankyla (estacion polar; KSAT/FMI operan alli) [VERIFICAR]

Un satelite, elevacion minima 5 deg.

| Orbita | % de tiempo en visibilidad | h/dia |
|---|---|---|
| LEO SSO 600 km (i=97.79) | 6.0 | 1.4 |
| LEO alta 2.000 km i=63.4 | 11.1 | 2.7 |
| MEO 8.000 km i=63.4 | 29.2 | 7.0 |
| MEO 20.000 km i=63.4 | 38.4 | 9.2 |
| GEO 35.786 km @25 E | 100.0 | 24.0 |
| Molniya 12 h, hp=600 km, i=63.4 | 81.5 | 19.6 |
| Tundra 24 h, e=0.25, i=63.4 | 68.3 | 16.4 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 73.0 | 17.5 |

## X-band 8,2 GHz · 20 W · ant. 0,5 m · GS 7,3 m

EIRP = 43.5 dBW · G/T estacion = 32.9 dB/K · ancho de haz del satelite = 5.12 deg · banda asignada 375 MHz a 1.0 bit/s/Hz.

| Orbita | R [km] | FSPL [dB] | C/N0 [dBHz] | Rb limitada por potencia [Mbit/s] | Rb efectiva [Mbit/s] | limitante |
|---|---|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 750 | 168.2 | 135.3 | 9475755 | 375 | ancho de banda |
| LEO alta 2.000 km i=63.4 | 2314 | 178.0 | 125.5 | 995538 | 375 | ancho de banda |
| MEO 8.000 km i=63.4 | 8666 | 189.5 | 114.0 | 70999 | 375 | ancho de banda |
| MEO 20.000 km i=63.4 | 20724 | 197.1 | 106.4 | 12416 | 375 | ancho de banda |
| GEO 35.786 km @25 E | 39344 | 202.6 | 100.9 | 3445 | 375 | ancho de banda |
| Molniya 12 h, hp=600 km, i=63.4 | 39638 | 202.7 | 100.8 | 3394 | 375 | ancho de banda |
| Tundra 24 h, e=0.25, i=63.4 | 46304 | 204.0 | 99.5 | 2487 | 375 | ancho de banda |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 43397 | 203.5 | 100.0 | 2831 | 375 | ancho de banda |

## X-band 8,2 GHz · 5 W · ant. 0,3 m · GS 3,7 m

EIRP = 33.0 dBW · G/T estacion = 26.1 dB/K · ancho de haz del satelite = 8.53 deg · banda asignada 375 MHz a 1.0 bit/s/Hz.

| Orbita | R [km] | FSPL [dB] | C/N0 [dBHz] | Rb limitada por potencia [Mbit/s] | Rb efectiva [Mbit/s] | limitante |
|---|---|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 750 | 168.2 | 117.9 | 175269 | 375 | ancho de banda |
| LEO alta 2.000 km i=63.4 | 2314 | 178.0 | 108.2 | 18414 | 375 | ancho de banda |
| MEO 8.000 km i=63.4 | 8666 | 189.5 | 96.7 | 1313 | 375 | ancho de banda |
| MEO 20.000 km i=63.4 | 20724 | 197.1 | 89.1 | 230 | 230 | potencia |
| GEO 35.786 km @25 E | 39344 | 202.6 | 83.5 | 64 | 64 | potencia |
| Molniya 12 h, hp=600 km, i=63.4 | 39638 | 202.7 | 83.5 | 63 | 63 | potencia |
| Tundra 24 h, e=0.25, i=63.4 | 46304 | 204.0 | 82.1 | 46 | 46 | potencia |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 43397 | 203.5 | 82.7 | 52 | 52 | potencia |

## Ka 26 GHz · 20 W · ant. 0,5 m · GS 7,3 m

EIRP = 53.5 dBW · G/T estacion = 40.7 dB/K · ancho de haz del satelite = 1.61 deg · banda asignada 1500 MHz a 1.0 bit/s/Hz.

| Orbita | R [km] | FSPL [dB] | C/N0 [dBHz] | Rb limitada por potencia [Mbit/s] | Rb efectiva [Mbit/s] | limitante |
|---|---|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 750 | 178.3 | 143.1 | 57158926 | 1500 | ancho de banda |
| LEO alta 2.000 km i=63.4 | 2314 | 188.0 | 133.3 | 6005211 | 1500 | ancho de banda |
| MEO 8.000 km i=63.4 | 8666 | 199.5 | 121.8 | 428276 | 1500 | ancho de banda |
| MEO 20.000 km i=63.4 | 20724 | 207.1 | 114.2 | 74892 | 1500 | ancho de banda |
| GEO 35.786 km @25 E | 39344 | 212.6 | 108.7 | 20779 | 1500 | ancho de banda |
| Molniya 12 h, hp=600 km, i=63.4 | 39638 | 212.7 | 108.6 | 20471 | 1500 | ancho de banda |
| Tundra 24 h, e=0.25, i=63.4 | 46304 | 214.1 | 107.3 | 15002 | 1500 | ancho de banda |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 43397 | 213.5 | 107.8 | 17079 | 1500 | ancho de banda |

## Demanda de datos frente a capacidad [CALCULADO]

Flujo bruto del instrumento, sin compresion:

| Sensor | Formato | Prof. | Cadencia | Tasa bruta |
|---|---|---|---|---|
| MWIR | 1280 x 1024 | 14 bit | 10 s | 1,8 Mbit/s |
| MWIR | 1280 x 1024 | 14 bit | 1 s | 18,4 Mbit/s |
| VIS pancromatico | 4096 x 4096 | 12 bit | 10 s | 20,1 Mbit/s |
| VIS pancromatico | 4096 x 4096 | 12 bit | 1 s | 201 Mbit/s |

Conclusion incomoda: **el enlace no es el cuello de botella en ninguna de las
orbitas altas.** Con 20 W y una antena de 0,5 m, el margen de potencia desde
46.000 km supera en dos ordenes de magnitud la tasa bruta de un FPA MWIR a
10 s. La frase "procesado a bordo es obligatorio" de
`investigacion_preliminar/02_fisica_y_resolucion.md` **no se sostiene con este
calculo**: el procesado a bordo se justifica por latencia, por coordinacion de
espectro y por coste de estacion, no por fisica del enlace. Hay que corregirlo.

Donde SI es cuello de botella: LEO. No por la tasa instantanea (la distancia es
minima y el C/N0 enorme) sino por el **tiempo de contacto**: ver la tabla de
visibilidad desde Sodankyla. Un LEO SSO ve una estacion polar una fraccion
pequena del dia, y la latencia media de entrega queda dominada por la espera al
siguiente pase, no por el enlace. Las orbitas altas entregan en segundos porque
el satelite que observa es el mismo que esta en visibilidad permanente.

