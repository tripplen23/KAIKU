# 04 — Entorno de radiacion  (D10.4)

Generado por `04_radiacion.py`. Dipolo centrado alineado, L = r/(Re cos^2 lambda). Umbral de atrapamiento: altitud > 1000 km [SUPUESTO]. Ventana 8 dias, paso 20 s.

**El modelo dipolar no reproduce la Anomalia del Atlantico Sur.** Para LEO eso subestima la dosis; para las HEO es irrelevante porque su dosis la domina el cruce del ecuador magnetico a radio alto.


## Geometria frente a los cinturones [CALCULADO]

`r_eq` = altitud y L en el cruce del plano ecuatorial, donde esta concentrado el flujo atrapado. Es el numero que decide.

| Orbita | h perigeo [km] | h apogeo [km] | altitud en cruce ecuatorial [km] | L en cruce ecuatorial | L minima con alt>1000 km |
|---|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 600 | 600 | 600 / 600 | 1.09 / 1.09 | n/a |
| LEO alta 2.000 km i=63.4 | 2000 | 2000 | 2000 / 2000 | 1.31 / 1.31 | 1.31 |
| MEO 8.000 km i=63.4 | 8000 | 8000 | 8000 / 8000 | 2.25 / 2.25 | 2.25 |
| MEO 20.000 km i=63.4 | 20000 | 20000 | 20000 / 20000 | 4.14 / 4.14 | 4.14 |
| GEO 35.786 km @25 E | 35786 | 35786 | 35786 / 35786 | 6.61 / 6.61 | 6.61 |
| Molniya 12 h, hp=600 km, i=63.4 | 600 | 39767 | 5745 / 5745 | 1.90 / 1.90 | 1.67 |
| Tundra 24 h, e=0.25, i=63.4 | 25245 | 46327 | 33151 / 33151 | 6.20 / 6.20 | 6.08 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 8100 | 43500 | 16064 / 16064 | 3.52 / 3.52 | 3.26 |

## Residencia por banda L y travesias del cinturon interno

| Orbita | travesias/dia del nucleo L1,2-2,5 | h/dia Proton interno L1,2-2,5 | h/dia Ranura L2,5-3,0 | h/dia Electron externo L3-7 | h/dia Exterior L>7 | indice exposicion rel. (GEO=1) [SUPUESTO] |
|---|---|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 0.0 | 0.00 | 0.00 | 0.00 | 0.00 | n/a (SAA, fuera del modelo dipolar) |
| LEO alta 2.000 km i=63.4 | 22.8 | 13.44 | 1.76 | 8.80 | 0.00 | 3.19 |
| MEO 8.000 km i=63.4 | 10.1 | 5.47 | 3.56 | 8.83 | 6.14 | 1.56 |
| MEO 20.000 km i=63.4 | 0.0 | 0.00 | 0.00 | 12.20 | 11.80 | 0.53 |
| GEO 35.786 km @25 E | 0.0 | 0.00 | 0.00 | 24.00 | 0.00 | 1.00 |
| Molniya 12 h, hp=600 km, i=63.4 | 4.1 | 2.17 | 0.62 | 2.98 | 17.81 | 0.62 |
| Tundra 24 h, e=0.25, i=63.4 | 0.0 | 0.00 | 0.00 | 5.27 | 18.73 | 0.26 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 0.0 | 0.00 | 0.00 | 7.18 | 16.82 | 0.33 |

## Pesos usados en el indice (sustituir por SPENVIS/AP9-AE9)

| Banda | L min | L max | peso [SUPUESTO] |
|---|---|---|---|
| Proton interno L1,2-2,5 | 1.2 | 2.5 | 100.0 |
| Ranura L2,5-3,0 | 2.5 | 3.0 | 5.0 |
| Electron externo L3-7 | 3.0 | 7.0 | 20.0 |
| Exterior L>7 | 7.0 | inf | 1.0 |

## Lectura para un detector MWIR criogenico

Los dos mecanismos que importan no son el mismo:

1. **TID (dosis ionizante total)** — afecta a la electronica de proximidad, al
   ROIC y a la optoelectronica. Se mitiga con blindaje y con componentes
   cualificados. Escala aproximadamente con el indice de la tabla anterior.
2. **DDD (dano por desplazamiento)** — lo causan los protones de >10 MeV del
   cinturon interno. Aumenta la corriente de oscuridad del FPA y genera pixeles
   calientes. **No se mitiga con blindaje razonable**: un proton de 50 MeV
   atraviesa varios mm de aluminio. Se mitiga bajando la temperatura de
   operacion (mas potencia de criogenerador) y con correccion de pixel vivo.
   Para un FPA MWIR, el DDD es el mecanismo que fija la vida util.

Consecuencia directa de la tabla: lo que separa las tres HEO no es la dosis
media, es **donde cruzan el ecuador magnetico**. Una orbita cuyo cruce
ecuatorial este por encima de L~3 no atraviesa el nucleo de protones y el DDD
sobre el FPA deja de ser el riesgo dominante. [CALCULADO]

