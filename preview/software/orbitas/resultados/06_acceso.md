# 06 — Coste de acceso  (D10.6)


## Delta-v desde GTO Kourou (Ariane 6), i=6 [m/s]

| Orbita | i objetivo [deg] | dV1 (apogeo GTO) | dV2 (apogeo final) | dV total | giro de plano en dV1 [deg] | % masa de propulsante, Isp=321 s | % masa de propulsante, Isp=1600 s |
|---|---|---|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 97.8 | 3070 | 9557 | 12627 | 12.7 | 98.2 | 55.3 |
| LEO alta 2.000 km i=63.4 | 63.4 | 2711 | 5237 | 7947 | 11.5 | 92.0 | 39.7 |
| MEO 8.000 km i=63.4 | 63.4 | 1243 | 4414 | 5657 | 3.2 | 83.4 | 30.3 |
| MEO 20.000 km i=63.4 | 63.4 | 406 | 3270 | 3676 | 0.6 | 68.9 | 20.9 |
| GEO 35.786 km @25 E | 0.0 | 3 | 1490 | 1493 | 0.0 | 37.8 | 9.1 |
| Molniya 12 h, hp=600 km, i=63.4 | 63.4 | 1862 | 53 | 1916 | 55.8 | 45.6 | 11.5 |
| Tundra 24 h, e=0.25, i=63.4 | 63.4 | 1992 | 1225 | 3218 | 38.6 | 64.0 | 18.5 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 65.0 | 1921 | 659 | 2580 | 44.9 | 55.9 | 15.2 |

## Delta-v desde GTO Cabo Canaveral (F9), i=27 [m/s]

| Orbita | i objetivo [deg] | dV1 (apogeo GTO) | dV2 (apogeo final) | dV total | giro de plano en dV1 [deg] | % masa de propulsante, Isp=321 s | % masa de propulsante, Isp=1600 s |
|---|---|---|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 97.8 | 3534 | 6796 | 10330 | 16.9 | 96.2 | 48.2 |
| LEO alta 2.000 km i=63.4 | 63.4 | 2813 | 2820 | 5633 | 12.3 | 83.3 | 30.2 |
| MEO 8.000 km i=63.4 | 63.4 | 1246 | 2893 | 4139 | 3.2 | 73.1 | 23.2 |
| MEO 20.000 km i=63.4 | 63.4 | 404 | 2380 | 2784 | 0.6 | 58.7 | 16.3 |
| GEO 35.786 km @25 E | 0.0 | 5 | 1801 | 1807 | 0.1 | 43.7 | 10.9 |
| Molniya 12 h, hp=600 km, i=63.4 | 63.4 | 1461 | 54 | 1515 | 35.0 | 38.2 | 9.2 |
| Tundra 24 h, e=0.25, i=63.4 | 63.4 | 1812 | 1153 | 2965 | 23.9 | 61.0 | 17.2 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 65.0 | 1672 | 598 | 2271 | 28.3 | 51.4 | 13.5 |

Nota: para LEO SSO la columna no tiene sentido operativo —nadie va a LEO desde una GTO—; se incluye solo para que la comparacion sea completa. El acceso real a LEO SSO es un rideshare directo.


## Azimut de lanzamiento y perdida de beneficio de rotacion

Condicion directa: cos(i) = cos(lat) * sin(Az). La perdida es frente a un lanzamiento al este desde el mismo sitio. [CALCULADO]

| Base | latitud [deg] | i=63,4 (Molniya/Tundra) | i=65 (TAP/ASBM) | i=97,8 (SSO) |
|---|---|---|---|---|
| Kourou (CSG) | 5.24 | Az=26.7 deg, perdida rot. 255 m/s | Az=25.1 deg, perdida rot. 267 m/s | Az=-7.8 deg, perdida rot. 526 m/s |
| Cabo Canaveral | 28.49 | Az=30.6 deg, perdida rot. 201 m/s | Az=28.7 deg, perdida rot. 212 m/s | Az=-8.9 deg, perdida rot. 472 m/s |
| Vandenberg | 34.74 | Az=33.0 deg, perdida rot. 174 m/s | Az=31.0 deg, perdida rot. 186 m/s | Az=-9.5 deg, perdida rot. 445 m/s |
| Andoya (NO) | 69.29 | no alcanzable | no alcanzable | Az=-22.6 deg, perdida rot. 228 m/s |
| Esrange (SE) | 67.89 | no alcanzable | no alcanzable | Az=-21.1 deg, perdida rot. 238 m/s |

## Cruce de la region protegida GEO (35.786 +/- 200 km, lat +/- 15 deg)

Definicion IADC / ISO 24113. Un cruce dentro de la region obliga a cribado de conjuncion continuo, a presupuesto de maniobra y complica el expediente de licencia y la ITU. [CALCULADO]

| Orbita | cruza r=42.164 km | latitud del cruce [deg] | dentro de la region protegida |
|---|---|---|---|
| LEO SSO 600 km (i=97.79) | no cruza | - | no |
| LEO alta 2.000 km i=63.4 | no cruza | - | no |
| MEO 8.000 km i=63.4 | no cruza | - | no |
| MEO 20.000 km i=63.4 | no cruza | - | no |
| GEO 35.786 km @25 E | orbita circular EN la region | 0,0 | si |
| Molniya 12 h, hp=600 km, i=63.4 | si | 59.8 / 59.8 | no |
| Tundra 24 h, e=0.25, i=63.4 | si | 12.9 / 12.9 | **SI** |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | si | 50.4 / 50.4 | no |
