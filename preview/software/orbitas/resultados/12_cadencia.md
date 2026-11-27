# 12 — Cadencia necesaria para que la pista sea defendible

Generado por `12_cadencia.py`. v_max = 16.0 nudos, v crucero = 12 nudos, GSD_eff = 450 m, sigma_posicion = GSD/5 = 90 m [SUPUESTO].


## C1 — Confusores esperados en la puerta de asociacion

Radio de puerta = v_max * dt. Criterio: < 0,1 confusores esperados. La densidad real del Golfo de Finlandia y del Barents sale del grabador AIS de D1; aqui se barre.

| dt [s] | radio de puerta [km] | area [km2] | rho=0.001 buques/km2 | rho=0.005 buques/km2 | rho=0.010 buques/km2 | rho=0.050 buques/km2 |
|---|---|---|---|---|---|---|
| 10 | 0.08 | 0.0 | 0.000 OK | 0.000 OK | 0.000 OK | 0.001 OK |
| 30 | 0.25 | 0.2 | 0.000 OK | 0.001 OK | 0.002 OK | 0.010 OK |
| 60 | 0.49 | 0.8 | 0.001 OK | 0.004 OK | 0.008 OK | 0.038 OK |
| 120 | 0.99 | 3.1 | 0.003 OK | 0.015 OK | 0.031 OK | 0.153 **ambiguo** |
| 300 | 2.47 | 19.2 | 0.019 OK | 0.096 OK | 0.192 **ambiguo** | 0.958 **ambiguo** |
| 600 | 4.94 | 76.6 | 0.077 OK | 0.383 **ambiguo** | 0.766 **ambiguo** | 3.831 **ambiguo** |
| 1800 | 14.82 | 689.6 | 0.690 **ambiguo** | 3.448 **ambiguo** | 6.896 **ambiguo** | 34.481 **ambiguo** |
| 3600 | 29.63 | 2758.5 | 2.758 **ambiguo** | 13.792 **ambiguo** | 27.585 **ambiguo** | 137.924 **ambiguo** |

## C2 — Resolucion temporal del evento

Incertidumbre del instante de la maniobra = dt/2, y distancia recorrida a 12 nudos en ese intervalo. Requisito propuesto: fechar el evento con +/- 2 min, es decir dt <= 240 s.

| dt [s] | incertidumbre del instante [min] | deriva a 12 kn en dt/2 [km] | cumple +/-2 min |
|---|---|---|---|
| 10 | 0.1 | 0.03 | OK |
| 30 | 0.2 | 0.09 | OK |
| 60 | 0.5 | 0.19 | OK |
| 120 | 1.0 | 0.37 | OK |
| 300 | 2.5 | 0.93 | insuficiente |
| 600 | 5.0 | 1.85 | insuficiente |
| 1800 | 15.0 | 5.56 | insuficiente |
| 3600 | 30.0 | 11.11 | insuficiente |

## C3 — Precision de velocidad por ajuste lineal

Para una traza rectilinea. **Este criterio no exige cadencia alta**: con 3 muestras a 30 min se obtiene 0,06 nudos. Es el argumento que no hay que usar para defender la persistencia.

| dt [s] | traza de 10 min | traza de 30 min | traza de 60 min |
|---|---|---|---|
| 10 | n=61, 0.065 m/s (0.13 kn) | n=181, 0.013 m/s (0.02 kn) | n=361, 0.005 m/s (0.01 kn) |
| 30 | n=21, 0.108 m/s (0.21 kn) | n=61, 0.022 m/s (0.04 kn) | n=121, 0.008 m/s (0.02 kn) |
| 60 | n=11, 0.143 m/s (0.28 kn) | n=31, 0.030 m/s (0.06 kn) | n=61, 0.011 m/s (0.02 kn) |
| 120 | n=6, 0.179 m/s (0.35 kn) | n=16, 0.041 m/s (0.08 kn) | n=31, 0.015 m/s (0.03 kn) |
| 300 | n=3, 0.212 m/s (0.41 kn) | n=7, 0.057 m/s (0.11 kn) | n=13, 0.022 m/s (0.04 kn) |
| 600 | n<3 | n=4, 0.067 m/s (0.13 kn) | n=7, 0.028 m/s (0.06 kn) |
| 1800 | n<3 | n<3 | n=3, 0.035 m/s (0.07 kn) |
| 3600 | n<3 | n<3 | n<3 |

## Conclusion de requisito temporal

Frente a una revisita de 30 min, el argumento **no** es la precision de
velocidad (C3 demuestra que 30 min bastan si la traza es recta y el blanco
esta identificado). El argumento es doble y es el siguiente:

| Criterio | Requisito | dt maximo |
|---|---|---|
| C1 asociacion sin AIS, rho=0.001 buques/km2 | <0,1 confusores esperados | **685 s** |
| C1 asociacion sin AIS, rho=0.005 buques/km2 | <0,1 confusores esperados | **307 s** |
| C1 asociacion sin AIS, rho=0.010 buques/km2 | <0,1 confusores esperados | **217 s** |
| C1 asociacion sin AIS, rho=0.050 buques/km2 | <0,1 confusores esperados | **97 s** |
| C2 fechar la maniobra a +/-2 min | dt <= 2*120 s | **240 s** |
| C3 velocidad a 0,5 kn sobre traza de 30 min | sigma_v < 0,26 m/s | no restrictivo (>1800 s) |

**Requisito de diseno propuesto: cadencia <= 60 s, objetivo 30 s.**
No "continuo", no 10 s. 60 s cumple los tres criterios con margen y es dos
ordenes de magnitud mas barato en datos y en procesado que 1 s.

Y la frase que hay que poder defender delante de un cliente:

> "Una revisita de 30 minutos te dice que un buque estuvo ahi. Con 60 segundos
> de cadencia te digo cuando redujo a 2 nudos, cuanto tiempo estuvo sobre el
> cable y cuando volvio a acelerar, con el instante fechado a +/-30 s y sin
> depender de que el AIS este encendido."

Eso es lo que no da una constelacion de revisita, por muchos satelites que
tenga: entre pases, la identidad del blanco se pierde. La persistencia no
compra resolucion, compra **continuidad de identidad**.

