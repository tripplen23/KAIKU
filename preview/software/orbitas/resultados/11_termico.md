# 11 — Radiador pasivo criogenico: viabilidad de primer orden

Generado por `11_termico.py`. eps=0,90, OLR=237 W/m2, albedo=0,30, S=1361 W/m2. Fuga de vista a la Tierra de un radiador anti-nadir con pantalla: 1% del factor de vista nadir [SUPUESTO].


## Carga ambiental terrestre segun el radio orbital

`F_e` = factor de vista de una placa que mira al centro de la Tierra. `T_eq nadir` = temperatura de equilibrio de esa placa sin ninguna otra carga: demuestra que un radiador criogenico **no puede mirar a la Tierra en ninguna orbita**, y por que el problema es de geometria y pantalla, no de area.

| Orbita | F_e apogeo | flujo nadir apogeo [W/m2] | T_eq nadir apogeo [K] | F_e perigeo | flujo nadir perigeo [W/m2] | T_eq nadir perigeo [K] |
|---|---|---|---|---|---|---|
| LEO SSO 600 km (i=97.79) | 0.8354 | 539.1 | 321 | 0.8354 | 539.1 | 321 |
| LEO alta 2.000 km i=63.4 | 0.5796 | 374.0 | 293 | 0.5796 | 374.0 | 293 |
| MEO 8.000 km i=63.4 | 0.1968 | 127.0 | 223 | 0.1968 | 127.0 | 223 |
| MEO 20.000 km i=63.4 | 0.0585 | 37.7 | 165 | 0.0585 | 37.7 | 165 |
| GEO 35.786 km @25 E | 0.0229 | 14.8 | 130 | 0.0229 | 14.8 | 130 |
| Molniya 12 h, hp=600 km, i=63.4 | 0.0191 | 12.3 | 125 | 0.8354 | 539.1 | 321 |
| Tundra 24 h, e=0.25, i=63.4 | 0.0146 | 9.5 | 117 | 0.0407 | 26.3 | 151 |
| TAP 16 h (ASBM): 8.100 x 43.500 km, i=65 | 0.0164 | 10.6 | 120 | 0.1941 | 125.2 | 223 |
| BASELINE Molniya hp=5.000 km | 0.0233 | 15.1 | 131 | 0.3142 | 202.8 | 251 |

## Area de radiador necesaria [m2], radiador anti-nadir con pantalla solar


### BASELINE Molniya hp=5.000 km (apogeo r=41745 km)

| T objetivo [K] | emision util [W/m2] | fuga terrestre [W/m2] | Q_int=0.2 W | Q_int=0.5 W | Q_int=1.0 W | Q_int=2.0 W |
|---|---|---|---|---|---|---|
| 80 | 2.09 | 0.151 | 0.103 (32x32 cm) | 0.258 (51x51 cm) | 0.516 (72x72 cm) | 1.031 (102x102 cm) |
| 110 | 7.47 | 0.151 | 0.027 (17x17 cm) | 0.068 (26x26 cm) | 0.137 (37x37 cm) | 0.273 (52x52 cm) |
| 130 | 14.58 | 0.151 | 0.014 (12x12 cm) | 0.035 (19x19 cm) | 0.069 (26x26 cm) | 0.139 (37x37 cm) |
| 150 | 25.84 | 0.151 | 0.008 (9x9 cm) | 0.019 (14x14 cm) | 0.039 (20x20 cm) | 0.078 (28x28 cm) |

### LEO SSO 600 km (r=6978 km)

| T objetivo [K] | emision util [W/m2] | fuga terrestre [W/m2] | Q_int=0.2 W | Q_int=0.5 W | Q_int=1.0 W | Q_int=2.0 W |
|---|---|---|---|---|---|---|
| 80 | 2.09 | 5.391 | inf | inf | inf | inf |
| 110 | 7.47 | 5.391 | 0.096 (31x31 cm) | 0.240 (49x49 cm) | 0.481 (69x69 cm) | 0.961 (98x98 cm) |
| 130 | 14.58 | 5.391 | 0.022 (15x15 cm) | 0.054 (23x23 cm) | 0.109 (33x33 cm) | 0.218 (47x47 cm) |
| 150 | 25.84 | 5.391 | 0.010 (10x10 cm) | 0.024 (16x16 cm) | 0.049 (22x22 cm) | 0.098 (31x31 cm) |

## Transitorio de perigeo (BASELINE 12 h, hp=5.000 km)

Capacidad termica del conjunto frio supuesta 800 J/K (~2 kg de aluminio a 110 K). Radiador de 0,15 m2.

| altitud umbral [km] | h por orbita por debajo | exceso de carga [W] | calentamiento acumulado [K] |
|---|---|---|---|
| 12000 | 1.98 | 0.094 | 0.8 |
| 15000 | 2.61 | 0.064 | 0.7 |
| 20000 | 3.76 | 0.034 | 0.6 |

## Veredicto de primer orden sobre IP-2

1. **El area no es el problema.** Desde el apogeo de cualquier HEO, mantener
   150 K con 1 W interno pide ~0,04 m2 y mantener 110 K con 1 W pide ~0,13 m2.
   Son placas de 20 a 36 cm de lado. Caben.
2. **La geometria si lo es.** La temperatura de equilibrio de una placa que
   mira a la Tierra es de 180 a 280 K segun el radio. El radiador tiene que
   mirar al espacio profundo y no ver nunca ni el Sol ni la Tierra. En una HEO
   con apogeo sobre el Artico y el Sol a 24 h en verano, eso obliga a una
   pantalla fija de dos etapas y restringe la actitud. **Es un requisito de
   configuracion, no un componente.**
3. **El perigeo no lo rompe.** Con el radiador apantallado, el exceso de carga
   en el paso bajo es de milivatios y el calentamiento acumulado del conjunto
   frio es de decimas de kelvin. La objecion "solo funciona en apogeo" no
   aplica al radiador; aplicaria a un radiador sin pantalla.
4. **Lo que de verdad decide es el parasito conductivo**, no el radiativo:
   soportes del plano focal, mazo y baffle. Un presupuesto de 0,2-0,5 W de
   parasitos es ambicioso pero no excepcional a 110 K; a 80 K no lo es.
   Por eso un detector T2SL/barrera que opere a 110-150 K cambia la ecuacion
   y uno que exija 80 K no.
5. **Acoplamiento con la radiacion que nadie menciona:** la corriente de
   oscuridad inducida por dano por desplazamiento crece fuertemente con la
   temperatura de operacion. Operar a 150 K en vez de 80 K **amplifica** el
   efecto del dano por protones. Es decir, la opcion "sin criogenerador" solo
   cierra si la orbita saca al satelite del cinturon de protones interno.
   IP-2 y la eleccion de perigeo son la misma decision. [CALCULADO en 08;
   magnitud del acoplamiento: VERIFICAR con datos de proveedor]

