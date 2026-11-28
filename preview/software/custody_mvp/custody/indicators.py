"""Indicadores de comportamiento anómalo sobre trazas AIS.

ESTADO DE CALIBRACIÓN: los umbrales de este fichero son INICIALES y NO están
calibrados. No existe en el repositorio un conjunto etiquetado de incidentes
tipo Eagle S (AIS histórico de dic-2024 del golfo: comprobado inexistente en
abierto, canal/iteracion_01/01_systems_engineer.md §5). Cada umbral lleva
abajo su justificación física o de procedimiento y su confianza. Sustituirlos
es cambiar un número en THRESHOLDS, no tocar código.

Trampas de interfaz que este módulo implementa explícitamente (si se omiten,
los indicadores dan cero alertas o las dan todas a la vez):
  T1  Un buque nunca desaparece del feed REST: el endpoint sigue sirviendo su
      último fix ~24 h. "Perdió AIS" = `timestampExternal` deja de avanzar.
      Se cumple porque el cargador deduplica por (mmsi, timestampExternal).
  T2  Un hueco en los datos no es un hueco en el AIS. IND-04 solo mira dentro
      de las ventanas de cobertura del log de polls.
  T3  El arranque en frío trae un fix de hasta 24 h de antigüedad por buque.
      Entre ese fix y el siguiente hay un salto que NO es comportamiento.
      Toda ventana exige gap interno <= MAX_GAP_S.
  T4  heading=511, sog=102.3, cog=360 son "no disponible", no valores
      físicos. Ya anulados en custody.ais.
"""
import hashlib
import math
import json
import logging
import statistics

from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import geo, motion

LOG = logging.getLogger("custody.ind")

THRESHOLDS = {
    # --- comunes
    "max_gap_s": 600,            # T3: salto máximo admitido dentro de una ventana
    "corridor_near_m": 3704.0,   # 2 NM: franja de interés sobre corredor trunk
    "corridor_close_m": 1852.0,  # 1 NM: proximidad estricta (IND-05)
    "corridor_buffer_m": 500.0,  # P2 del CTO: buffer al eje del cable

    # --- IND-01 velocidad baja sostenida sobre corredor
    "slow_lo_kn": 1.0,           # P3 del CTO (02_cto.md E.1)
    "slow_hi_kn": 5.0,           # P3 del CTO: era 6.0 en la primera version
    "slow_window_s": 1800,       # 30 min, P3 del CTO: era 1200
    "under_power_kn": 2.5,       # P1 del CTO: techo fisico de deriva pasiva
    "slow_min_net_nm": 0.5,      # sigue haciendo camino: no es fondeo
    "slow_navstat_frac": 0.8,
    "slow_p90_margin_kn": 0.0,   # p90 de sog tambien dentro de la banda

    # --- IND-02 divergencia COG-HDG
    # P4 del CTO. El umbral instantaneo de 20 grados NO se usa: medido sobre
    # 5.141 fixes en movimiento, dispara sobre el 4,12 % (02_cto.md A.3). Lo
    # que se mide es el SESGO: mediana de (COG - HDG) con SIGNO CONSTANTE.
    "divergence_median_deg": 8.0,
    "divergence_sign_frac": 0.9,          # fraccion de fixes con el mismo signo
    "divergence_max_plausible_deg": 90.0,
    "divergence_window_s": 1200,          # 20 min, P4
    "divergence_min_sog_kn": 3.0,         # P4

    # --- IND-03 loitering
    "loiter_max_sog_kn": 1.0,
    "loiter_window_s": 3600,     # 60 min
    "loiter_max_net_nm": 0.5,

    # --- IND-07 salto de posicion imposible
    # 45 nudos es el techo practico de un mercante o un remolcador. Los
    # hidroalas y las lanchas rapidas pasan de ahi, pero no son lo que vemos.
    # Por debajo de este umbral no se habla: el ruido de GPS con dos fixes
    # muy juntos en el tiempo produce velocidades altas sin que pase nada.
    "impossible_kn": 45.0,
    "impossible_min_dist_m": 2000.0,   # salto minimo para no confundir con ruido
    "impossible_min_dt_s": 5.0,        # dos fixes al mismo segundo no miden nada

    # --- IND-04 hueco de AIS
    "gap_s": 1800,               # 30 min

    # --- IND-06 encuentro barco a barco (P8 del CTO)
    "encounter_max_dist_m": 500.0,
    "encounter_max_sog_kn": 3.0,
    "encounter_window_s": 1800,   # 30 min
    "encounter_bin_s": 60,        # cadencia de sondeo del grabador
    # «En la mar» tiene que significar algo geométrico. La máscara de puertos
    # de OSM NO basta: medido, de 45 candidatos de IND-06 en la primera pasada
    # solo 16 cayeron dentro de ella y el resto eran flotas de prácticos y
    # embarcaciones de trabajo atracadas juntas en bases que OSM no tiene
    # poligonizadas. Se exige además distancia a la costa.
    "min_coast_dist_m": 1852.0,   # 1 NM

    # --- IND-05 proximidad ponderada por profundidad
    "anchor_max_depth_m": 80.0,
    "anchor_min_depth_m": 10.0,

    # --- IND-08 anomalía cinemática aprendida (Gaussian MLP 14->64->64->4)
    "motion_min_dt_s": 60,
    "motion_max_dt_s": 300,
    "motion_min_sog_kn": 2.0,
    "motion_max_sog_kn": 30.0,
    "motion_radial_z": 2.447746830680816,  # sqrt(chi2_{2, 0.95}) = 2.45 sigma
    "motion_min_dv_kn": 1.0,
    "motion_min_decel_kn": 0.8,
    "motion_min_hits": 2,
    "motion_corridor_m": 5000.0,           # 5 km alrededor de corredores submarinos

    # --- clasificación de salida
    # IND-05 es EXPOSICIÓN, no alerta. Medido en la pasada en que se tomo la decision: 71 de 75
    # "alertas" eran ferries de línea Helsinki-Tallinn cruzando cables, porque
    # cruzarlos es su ruta. Una capa de alertas dominada por tráfico regular de
    # pasaje no sirve a un operador. IND-05 pondera, no avisa.
    # IND-06 entra aquí por el mismo criterio y con su propia medida: de 61
    # episodios de pareja, la máscara de puerto suprime 29 y el criterio de 1 NM
    # de costa otros 17; quedan 15 encuentros y LOS 15 son grupos de lanchas de
    # práctico amarradas en sus bases (Harmaja, Emäsalo), que OSM no tiene
    # poligonizadas y que están a 2,6 y 7,5 km de la costa. Falsa alarma 15/15.
    # No se filtra por shipType=50: el tipo es autodeclarado y falsificable.
    # Vuelve a ser alerta cuando exista la máscara oficial de zonas de espera
    # (petición al CEO, sección «Datos que no pude obtener»).
    # IND-03 entra por el mismo criterio: de 10 alertas, 8 son lanchas de
    # practico amarradas en Harmaja (24,974 E / 60,105 N) y Emasalo (26,445 E /
    # 60,275 N) y las otras 2 son transpondedores AIS de prueba fijos
    # ("FURUNOP", "NAVI TEST") con desplazamiento neto de 4 y 3 metros en una
    # hora. Falsa alarma 10/10.
    "exposure_only": ["IND-03", "IND-05", "IND-06"],

    # --- IND-04: borde del AOI
    # Un hueco ABIERTO cuyo ultimo fix esta pegado al borde del AOI no es un
    # buque que calla: es un buque que se ha ido del recorte. Medido: de 14
    # huecos abiertos, varios con el ultimo fix a < 1 km del meridiano 22,0.
    "aoi_edge_margin_m": 9260.0,   # 5 NM

    # --- puntuación compuesta
    "weights": {"IND-01": 0.30, "IND-02": 0.20, "IND-03": 0.15,
                "IND-04": 0.20, "IND-05": 0.15, "IND-06": 0.25,
                "IND-08": 0.25},
}

JUSTIFICATION = {
    "IND-07": {
        "what": "Dos posiciones consecutivas implican una velocidad que el "
                "casco no puede alcanzar.",
        "why": "45 nudos es el techo practico del trafico que vemos: mercantes, "
               "petroleros, remolcadores y ferris. Por encima, la trayectoria "
               "es fisicamente imposible, no solo rara.",
        "confidence": "ALTA en la deteccion, NULA en la causa. Que el salto es "
                      "imposible es aritmetica. Por que ocurre -- MMSI "
                      "compartido, suplantacion, error de decodificacion -- "
                      "esta herramienta no lo determina y no lo afirma.",
        "measured": "1.779 saltos en 28 MMSI de 1.253 trazas (2026-11-11). "
                    "Peor caso: 10.420 kn, 160 km en 30 s.",
    },
    "IND-01": (
        "Un mercante en tránsito por el golfo navega a 10-14 kn. Arrastrar el "
        "ancla y su cadena frena varios nudos pero el buque sigue avanzando con "
        "máquina: sog=0 es fondeado o amarrado, no arrastrando. Por eso es una "
        "BANDA [1,6] kn y no un techo, y por eso se exige desplazamiento neto "
        ">=0,5 NM y navStat=0. 20 min filtra reducciones de velocidad por "
        "práctico, tráfico o maniobra de rumbo. Confianza: Media-Baja, umbral "
        "no calibrado contra un caso real."),
    "IND-02": (
        "P4 de canal/iteracion_02/02_cto.md E.1. NO es un umbral instantáneo de "
        "divergencia: el CTO midió que |COG-HDG| > 20 grados con SOG >= 2 kn "
        "dispara sobre el 4,12 % de 5.141 fixes en movimiento, lo que lo hace "
        "inusable como alarma. Lo que se mide es el SESGO: la mediana de "
        "(heading - cog) CON SIGNO, exigiendo el mismo signo en >= 90 % de la "
        "ventana, |mediana| >= 8 grados, SOG >= 3 kn y 20 min. Un buque que "
        "arrastra algo por una banda guiña siempre hacia el mismo lado; la "
        "deriva por viento cambia de signo cuando el viento rota. Requiere "
        "heading: el 12,5 % de los fixes trae 511 = no disponible. "
        "FALTA P5 (invariancia del signo frente al viento, ERA5/CMEMS): sin "
        "él este indicador no separa arrastre de deriva por viento sostenido. "
        "Confianza: Media."),
    "IND-03": (
        "EXPOSICIÓN, no alerta. MEDIDO: de 63 episodios, 28 suprimidos por máscara "
        "de puerto y 25 por el criterio de 1 NM de costa; de las 10 salidas "
        "restantes, 8 son lanchas de práctico "
        "amarradas en Harmaja y Emäsalo y las otras 2 son transpondedores AIS de "
        "prueba fijos (`FURUNOP`, `NAVI TEST`) con 4 y 3 metros de desplazamiento "
        "neto en una hora. Falsa alarma 10/10, por la misma causa que IND-06: no "
        "existe máscara oficial de estaciones de práctico ni lista de "
        "transpondedores fijos conocidos. "
        "1 kn está por debajo de la velocidad de gobierno de un mercante. 60 min "
        "excluye esperas cortas de práctico y de esclusa. navStat 1 (at anchor) "
        "y 5 (moored) se excluyen por declaración del propio buque, y la "
        "posición se contrasta contra una máscara de puertos y fondeaderos de "
        "OSM: sin esa máscara, medido en iteración 01, ~13 % de los candidatos "
        "son buques atracados que mantienen navStat=0. Confianza: Alta en la "
        "mecánica, Media en el umbral."),
    "IND-04": (
        "Un Class A en navegación transmite posición cada 2-10 s. 30 min son "
        ">=180x el nominal: no es pérdida de recepción puntual. El suelo de "
        "granularidad es de 60 s porque esa es la cadencia de sondeo (el "
        "upstream declara max-age=60). Se distingue hueco CERRADO (el AIS "
        "vuelve: evidencia fuerte) de hueco ABIERTO (sigue mudo al final del "
        "registro: indistinguible de salida del alcance VHF costero). "
        "Confianza: Alta en la detección, Baja en la atribución de intención."),
    "IND-06": (
        "P8 de canal/iteracion_02/02_cto.md E.1, que replica el `AtSeaEncounter` "
        "que EMSA opera desde 2016. Dos buques a < 500 m con ambos por debajo de "
        "3 kn durante > 30 min, fuera de la máscara de puerto y fondeadero (la "
        "advertencia explícita de EMSA) y a MÁS DE 1 NM DE LA COSTA. Esto "
        "último no es decorativo: en la primera pasada salieron 45 candidatos y "
        "la máscara de OSM solo suprimió 16; el resto eran flotas de prácticos y "
        "embarcaciones de trabajo atracadas juntas en bases que OSM no tiene "
        "poligonizadas. «En la mar» tiene que ser un criterio geométrico, no "
        "depender de que un tercero haya dibujado un polígono. Las posiciones se alinean en cubos de "
        "60 s, que es la cadencia de sondeo del grabador: no se interpola la "
        "posición de ningún buque para rellenar el hueco del otro. Por debajo de "
        "500 m dos mercantes están dentro de la distancia de maniobra mutua; por "
        "encima de 30 min no es un cruce. Confianza: Alta en el cómputo, Baja en "
        "la intención: un encuentro es un hecho, no un delito."),
    "IND-05": (
        "EXPOSICIÓN, no alerta. "
        "La cadena de un mercante son típicamente 10-13 grilletes, 275-357 m. "
        "Fondear exige scope de 4-6 veces la profundidad, así que un molinete "
        "mercante convencional trabaja hasta del orden de 60-80 m y por encima "
        "de ~100 m no puede largar y recuperar. Profundidad > 80 m sobre el "
        "corredor hace físicamente inverosímil el arrastre de ancla contra ese "
        "activo. ADVERTENCIA: el golfo de Finlandia es mayoritariamente más "
        "somero que 100 m, así que dentro del golfo este filtro descarta poco; "
        "sirve para ORDENAR y para el Báltico central. El suelo de 10 m descarta "
        "canales balizados y atraques, donde el tráfico maniobra por oficio y "
        "los cables llegan enterrados o acorazados. Confianza: Alta en la "
        "física, Alta en el dato de profundidad (EMODnet DTM)."),
    "IND-08": {
        "what": (
            "Al menos dos pasos consecutivos o sostenidos de velocidad "
            "(Δv_east, Δv_north) en 60-300 s con frenada longitudinal "
            "(Δsog <= -0,8 kn y |Δv| >= 1,0 kn) a <= 5 km de un corredor "
            "de cable o gasoducto submarino se salen de la elipse de "
            "confianza al 95 % predicha por el modelo cinemático gaussiano "
            "aprendido con campo de flujo histórico (ShipMotionGaussianMLP v3, 14->64->64->4)."
        ),
        "why": (
            "IND-01 exige 30 minutos sostenidos entre 1 y 5 kn sobre el corredor. "
            "El inicio de un arrastre de ancla o una frenada brusca en mar abierto "
            "produce en solo 60-300 s por paso una caída longitudinal de velocidad "
            "(Δsog <= -0,8 kn) y deriva transversal que viola la inercia normal del "
            "buque condicionada por su aceleración previa causal (prev_dv_east, "
            "prev_dv_north), su maniobrabilidad (is_maneuver_vessel) y el campo de "
            "flujo histórico en 8 octantes (flow_dv_east, flow_dv_north, has_flow) "
            "(radial_z > sqrt(chi2_{2, 0.95}) = 2,45 sigma, |Δv| >= 1,0 kn y "
            "motion_min_hits = 2 pasos anómalos) dentro del dominio válido de "
            "tránsito (60-300 s, 2-30 kn), a <= 5 km de un corredor submarino "
            "(motion_corridor_m = 5.000 m) y fuera de la máscara de puertos."
        ),
        "confidence": (
            "ALTA en la rareza estadística del salto cinemático (cobertura "
            "empírica 2D al 95 % = 94,94 % y marginal = 95,90 % en test 2024 del "
            "golfo de Finlandia; 93,55 % 2D / 95,08 % marginal sin reentrenamiento "
            "en 1.122 MMSI no vistos de DMA 2026-11-20; y 87,63 % 2D / 90,70 % "
            "marginal en 803 MMSI bajo temporal invernal de 23,4-29,0 kn en DMA "
            "2026-02-04). MEDIA en la atribución: una reducción brusca de máquina "
            "o aproximación a fondeadero también produce desaceleración; cuando no "
            "hay forzamiento metoceánico en línea se declara explícitamente "
            "forcing_source='none'. El discriminador Tier-2 (regresión logística L2 "
            "entrenada en 1.500 episodios simulados 3-DOF Fossen + catenaria en 3 "
            "clases de casco) puntúa frenada, deriva unilateral |HDG-COG| y "
            "profundidad <= 110 m como triaje físico, NO prueba de fondeo."
        ),
        "measured": (
            "Entrenado sobre 41.539 pasos de entrenamiento (60.000 pasos muestreados "
            "en total y 9.923 celdas de flujo en 8 octantes de 1.910.555 transiciones "
            "de entrenamiento) del golfo de Finlandia (otoño 2024) en 1.486 MMSI de "
            "entrenamiento, y validado sin reentrenamiento sobre tres bancos "
            "independientes: test 2024 GoF (8.690 pasos en 319 MMSI, 94,94 % 2D / "
            "95,90 % marginal al 95 % CI; giros en canal |Δrumbo| >= 10° con "
            "RMSE de rumbo 15,03° vs 15,95° Pers), DMA 2026-11-20 (20.000 pasos en "
            "1.122 MMSI, 93,55 % 2D / 95,08 % marginal; recall del 53,4 % a -0,5 kn, "
            "91,8 % a -1,0 kn y 98,0 % a -1,5 kn) y temporal invernal DMA "
            "2026-02-04 (20.000 pasos en 803 MMSI con viento de 23,4-29,0 kn, "
            "87,63 % 2D / 90,70 % marginal; recall del 59,6 % a -0,5 kn, 90,2 % "
            "a -1,0 kn y 98,6 % a -1,5 kn)."
        ),
        "en": {
            "what": (
                "At least two 60-300 s velocity transitions (dv_east, dv_north) "
                "with longitudinal braking (dsog <= -0.8 kn and |dv| >= 1.0 kn) "
                "within 5 km of a subsea cable or pipeline corridor fall outside "
                "the 95% 2D confidence ellipse predicted by the learned flow-aware "
                "Gaussian motion model (ShipMotionGaussianMLP v3, 14->64->64->4)."
            ),
            "why": (
                "IND-01 requires 30 minutes of sustained 1-5 kn speed over a corridor. "
                "Early anchor-drag onset or an abrupt open-water deceleration produces "
                "within 60-300 s per step an along-track speed drop (dsog <= -0.8 kn) "
                "and cross-track crabbing drift that exceeds the vessel's learned "
                "inertia envelope conditioned on causal prior step acceleration "
                "(prev_dv_east, prev_dv_north), hull maneuverability class "
                "(is_maneuver_vessel), and the 8-octant historical traffic flow field "
                "(flow_dv_east, flow_dv_north, has_flow) (radial_z > sqrt(chi2_{2, 0.95}) = "
                "2.45 sigma, |dv| >= 1.0 kn, and motion_min_hits = 2 anomalous steps) inside "
                "the valid transit domain (60-300 s, 2-30 kn), within <= 5 km of a subsea "
                "cable/pipeline corridor (motion_corridor_m = 5,000 m), and outside port zones."
            ),
            "confidence": (
                "HIGH on statistical kinematic anomaly (94.94% 2D / 95.90% marginal "
                "95% CI coverage on 2024 Gulf of Finland test; 93.55% 2D / 95.08% "
                "marginal across 1,122 unseen 2026-11-20 DMA MMSIs; and 87.63% 2D / "
                "90.70% marginal across 803 unseen MMSIs during the 2026-02-04 "
                "23.4-29.0 kn winter storm). MEDIUM on intent: sharp engine "
                "reductions or anchorage approaches also produce braking residuals; "
                "when live metocean forcing is absent, forcing_source='none' is "
                "explicitly recorded. The Tier-2 physics-sim discriminator (L2 "
                "logistic regression trained on 1,500 simulated 3-DOF Fossen + "
                "catenary episodes across 3 hull classes) scores braking, "
                "unilateral |HDG-COG| crab, and EMODnet seabed reachability <= 110 m "
                "as a triage aid, NOT proof of anchor deployment."
            ),
            "measured": (
                "Trained on 41,539 train (60,000 sampled total, plus 9,923 8-octant flow "
                "cells from 1,910,555 train-MMSI transitions) Gulf of Finland steps "
                "across 1,486 train MMSIs (Autumn 2024) and validated across 3 "
                "independent benchmarks: 2024 GoF held-out test (8,690 steps across "
                "319 MMSIs, 94.94% 2D / 95.90% marginal 95% CI; curved-lane turns "
                "|Δbearing| >= 10° Bearing RMSE 15.03° vs 15.95° Pers), 2026-11-20 DMA calm "
                "day (20,000 steps across 1,122 MMSIs, 93.55% 2D / 95.08% marginal; "
                "53.4% recall at -0.5 kn, 91.8% at -1.0 kn, 98.0% at -1.5 kn), and "
                "2026-02-04 DMA winter high-wind day (20,000 steps across 803 MMSIs "
                "at 23.4-29.0 kn wind, 87.63% 2D / 90.70% marginal; 59.6% recall at "
                "-0.5 kn, 90.2% at -1.0 kn, 98.6% at -1.5 kn)."
            ),
        },
        "es": {
            "what": (
                "Al menos dos pasos consecutivos o sostenidos de velocidad "
                "(Δv_east, Δv_north) en 60-300 s con frenada longitudinal "
                "(Δsog <= -0,8 kn y |Δv| >= 1,0 kn) a <= 5 km de un corredor "
                "de cable o gasoducto submarino se salen de la elipse de "
                "confianza al 95 % predicha por el modelo cinemático gaussiano "
                "aprendido con campo de flujo histórico (ShipMotionGaussianMLP v3, 14->64->64->4)."
            ),
            "why": (
                "IND-01 exige 30 minutos sostenidos entre 1 y 5 kn sobre el corredor. "
                "El inicio de un arrastre de ancla o una frenada brusca en mar abierto "
                "produce en solo 60-300 s por paso una caída longitudinal de velocidad "
                "(Δsog <= -0,8 kn) y deriva transversal que viola la inercia normal del "
                "buque condicionada por su aceleración previa causal (prev_dv_east, "
                "prev_dv_north), su maniobrabilidad (is_maneuver_vessel) y el campo de "
                "flujo histórico en 8 octantes (flow_dv_east, flow_dv_north, has_flow) "
                "(radial_z > sqrt(chi2_{2, 0.95}) = 2,45 sigma, |Δv| >= 1,0 kn y "
                "motion_min_hits = 2 pasos anómalos) dentro del dominio válido de "
                "tránsito (60-300 s, 2-30 kn), a <= 5 km de un corredor submarino "
                "(motion_corridor_m = 5.000 m) y fuera de la máscara de puertos."
            ),
            "confidence": (
                "ALTA en la rareza estadística del salto cinemático (cobertura "
                "empírica 2D al 95 % = 94,94 % y marginal = 95,90 % en test 2024 del "
                "golfo de Finlandia; 93,55 % 2D / 95,08 % marginal sin reentrenamiento "
                "en 1.122 MMSI no vistos de DMA 2026-11-20; y 87,63 % 2D / 90,70 % "
                "marginal en 803 MMSI bajo temporal invernal de 23,4-29,0 kn en DMA "
                "2026-02-04). MEDIA en la atribución: una reducción brusca de máquina "
                "o aproximación a fondeadero también produce desaceleración; cuando no "
                "hay forzamiento metoceánico en línea se declara explícitamente "
                "forcing_source='none'. El discriminador Tier-2 (regresión logística L2 "
                "entrenada en 1.500 episodios simulados 3-DOF Fossen + catenaria en 3 "
                "clases de casco) puntúa frenada, deriva unilateral |HDG-COG| y "
                "profundidad <= 110 m como triaje físico, NO prueba de fondeo."
            ),
            "measured": (
                "Entrenado sobre 41.539 pasos de entrenamiento (60.000 pasos muestreados "
                "en total y 9.923 celdas de flujo en 8 octantes de 1.910.555 transiciones "
                "de entrenamiento) del golfo de Finlandia (otoño 2024) en 1.486 MMSI de "
                "entrenamiento, y validado sin reentrenamiento sobre tres bancos "
                "independientes: test 2024 GoF (8.690 pasos en 319 MMSI, 94,94 % 2D / "
                "95,90 % marginal al 95 % CI; giros en canal |Δrumbo| >= 10° con "
                "RMSE de rumbo 15,03° vs 15,95° Pers), DMA 2026-11-20 (20.000 pasos en "
                "1.122 MMSI, 93,55 % 2D / 95,08 % marginal; recall del 53,4 % a -0,5 kn, "
                "91,8 % a -1,0 kn y 98,0 % a -1,5 kn) y temporal invernal DMA "
                "2026-02-04 (20.000 pasos en 803 MMSI con viento de 23,4-29,0 kn, "
                "87,63 % 2D / 90,70 % marginal; recall del 59,6 % a -0,5 kn, 90,2 % "
                "a -1,0 kn y 98,6 % a -1,5 kn)."
            ),
        },
    },
}


# Trazabilidad contra el catálogo del CTO (canal/iteracion_02/02_cto.md E.1).
CTO_MAPPING = {
    "IND-01": "P3 (banda de arrastre 1,0-5,0 kn >=30 min) + P2 (corredor) + "
              "P1 (techo físico de deriva, bandera under_power_p1)",
    "IND-02": "P4 (sesgo unilateral de COG-HDG). P5 (invariancia frente al "
              "viento) NO implementado: exige ERA5/CMEMS",
    "IND-03": "no está en E.1; el más próximo es P8 (encuentro barco a barco), "
              "que exige pares de trazas y NO está implementado",
    "IND-04": "P6 (hueco de AIS corregido por cobertura)",
    "IND-05": "P2 (buffer al eje del cable; aquí 1 NM con tier de 500 m) "
              "ponderado por batimetría",
}
CTO_MAPPING["IND-06"] = "P8 (encuentro barco a barco), equivalente al AtSeaEncounter de EMSA"
CTO_MAPPING["IND-08"] = (
    "P3/P7 (residuo cinemático aprendido con MLP gaussiano v3 14->64->64->4 y campo "
    "de flujo histórico sobre pasos de 60-300 s, umbral radial 2D chi2_2 al 95 % = 2,45 sigma)"
)

NOT_IMPLEMENTED = {
    "P5": "invariancia del signo de COG-HDG frente al viento. Falta ERA5/CMEMS WIND",
    "P7": "residuo de deriva contra corriente. Falta CMEMS PHY 003_006",
    "P9": "contrafáctico de daño. Bloqueado: t1 (hora del fallo del activo) no es abierto",
    "P10": "desviación del grafo de rutas. Exige >=30 días de histórico",
    "P11": "autoencoder contextual. Fuera de alcance",
    "P12": "cambio de calado. Campo declarado a mano, no observación",
}


# Tipos AIS cuya operativa normal INCLUYE ir despacio o parado junto a
# cualquier cosa. No se filtran (el tipo es autodeclarado y falsificable),
# pero se marcan para que el operador lo vea sin abrir otra pestana.
SERVICE_CRAFT = {30: "fishing", 31: "towing", 32: "towing long", 33: "dredging",
                 34: "diving ops", 35: "military ops", 50: "pilot vessel",
                 51: "SAR", 52: "tug", 53: "port tender", 54: "anti-pollution",
                 55: "law enforcement"}
SHIP_TYPE = dict(SERVICE_CRAFT)
SHIP_TYPE.update({0: "no disponible", 36: "sailing", 37: "pleasure craft",
                  60: "passenger", 70: "cargo", 80: "tanker", 90: "other"})


# --------------------------------------------------------------- utilidades

def _nm(m):
    return m / geo.NM


def _signed_diff(heading, cog):
    """(heading - cog) normalizado a (-180, 180]. Positivo = proa a estribor
    del rumbo sobre el fondo."""
    d = (heading - cog + 180.0) % 360.0 - 180.0
    return d


def _bump(counters, key, point=None, extra=None):
    """Cuenta una supresion y, si se da el punto, la guarda para el visor.

    Sin esto el usuario ve "32 suprimidas por mascara de puerto" y tiene que
    creerselo. Con el punto puede abrir la capa y mirar cual.
    """
    if point is not None and counters is not None:
        ev = counters.setdefault("_events", [])
        if len(ev) < 1200:          # tope: la capa es para inspeccionar, no un volcado
            rec = {"key": key, "lon": point["lon"], "lat": point["lat"],
                   "mmsi": point.get("mmsi"), "ts": point.get("ts")}
            if extra:
                rec.update(extra)
            ev.append(rec)
    return _bump_count(counters, key)


def _bump_count(counters, key):
    if counters is not None:
        counters[key] = counters.get(key, 0) + 1


def _quantile(xs, q):
    """Cuantil por interpolacion lineal. statistics.quantiles exige n>=2 y
    devuelve cortes, no el valor pedido; esto es mas directo."""
    ys = sorted(xs)
    if not ys:
        return None
    if len(ys) == 1:
        return ys[0]
    pos = q * (len(ys) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ys) - 1)
    return ys[lo] + (ys[hi] - ys[lo]) * (pos - lo)


def _windows(track, span_s, max_gap_s):
    """Ventanas maximales de fixes consecutivos sin salto > max_gap_s y con
    duración >= span_s. Devuelve (i0, i1) inclusive."""
    out = []
    n = len(track)
    i = 0
    while i < n - 1:
        j = i
        while j + 1 < n and (track[j + 1]["ts"] - track[j]["ts"]) <= max_gap_s * 1000:
            j += 1
        if j > i and (track[j]["ts"] - track[i]["ts"]) >= span_s * 1000:
            out.append((i, j))
        i = j + 1 if j > i else i + 1
    return out


def _sub(track, i0, i1, span_s):
    """Ventanas minimales [a, b] con duración >= span_s, una por cada b.

    Minimales a propósito: una ventana más larga de lo necesario diluye la
    mediana de sog y esconde el episodio dentro del tránsito normal.
    """
    res = []
    a = i0
    need = span_s * 1000
    for b in range(i0, i1 + 1):
        while a < b and (track[b]["ts"] - track[a + 1]["ts"]) >= need:
            a += 1
        if (track[b]["ts"] - track[a]["ts"]) >= need:
            res.append((a, b))
    return res


def _net_nm(track, a, b):
    return _nm(geo.haversine_m(track[a]["lon"], track[a]["lat"],
                               track[b]["lon"], track[b]["lat"]))


def _mid(track, a, b):
    return track[(a + b) // 2]


def _evidence(track, a, b):
    return {"fix_keys": [[track[a]["mmsi"], track[a]["ts"]],
                         [track[b]["mmsi"], track[b]["ts"]]],
            "n_fixes": b - a + 1,
            "src_files": sorted({f.get("src_file") for f in track[a:b + 1]
                                 if f.get("src_file")}),
            "t_start_ms": track[a]["ts"], "t_end_ms": track[b]["ts"],
            "duration_s": (track[b]["ts"] - track[a]["ts"]) / 1000.0}


# --------------------------------------------------------------- indicadores

def ind01_slow_on_corridor(track, corridor_idx, th, depth_grid=None,
                           port_mask=None, counters=None):
    out = []
    for i0, i1 in _windows(track, th["slow_window_s"], th["max_gap_s"]):
        for a, b in _sub(track, i0, i1, th["slow_window_s"]):
            seg = track[a:b + 1]
            sogs = [f["sog"] for f in seg if f["sog"] is not None]
            if len(sogs) < 3:
                continue
            med = statistics.median(sogs)
            lo_q, hi_q = _quantile(sogs, 0.10), _quantile(sogs, 0.90)
            # La banda se exige sobre p10 y p90, no sobre la mediana. Con la
            # mediana, un practico que para 10 min y luego corre a 12 kn pasa
            # el filtro: medido, dos de los seis candidatos iniciales eran
            # lanchas de practico. Arrastrar un ancla es lento TODO el rato.
            if not (th["slow_lo_kn"] <= lo_q and
                    hi_q <= th["slow_hi_kn"] + th["slow_p90_margin_kn"]):
                continue
            ns = [f["navStat"] for f in seg]
            if ns.count(0) / len(ns) < th["slow_navstat_frac"]:
                continue
            if _net_nm(track, a, b) < th["slow_min_net_nm"]:
                continue
            ds = [corridor_idx.nearest(f["lon"], f["lat"]) for f in seg]
            if any(d is None or d > th["corridor_near_m"] for d, _ in ds):
                continue
            dmin, payload = min(ds, key=lambda x: x[0])
            mid = _mid(track, a, b)
            hit = port_mask.hit(mid["lon"], mid["lat"]) if port_mask else None
            if hit:
                # Se cuenta una supresion por EPISODIO, no por cada ventana
                # deslizante: si no, el contador mide el muestreo y no el
                # numero de falsos positivos evitados.
                _bump(counters, "port_mask_suppressed_IND-01", mid, {"mask": hit})
                break
            depth = depth_grid.depth_at(mid["lon"], mid["lat"]) if depth_grid else None
            if depth is not None and depth < th["anchor_min_depth_m"]:
                _bump(counters, "too_shallow_suppressed_IND-01", mid, {"depth_m": depth})
                break
            ev = _evidence(track, a, b)
            ev.update({"sog_median_kn": round(med, 2),
                       "sog_p10_kn": round(lo_q, 2), "sog_p90_kn": round(hi_q, 2),
                       # P1 del CTO: por encima de 2,5 kn sostenidos la deriva
                       # pasiva no explica el movimiento; va con maquina.
                       "under_power_p1": bool(lo_q >= th["under_power_kn"]),
                       "within_500m_buffer": bool(dmin <= th["corridor_buffer_m"]),
                       "depth_m": depth,
                       "sog_min_kn": min(sogs), "sog_max_kn": max(sogs),
                       "net_displacement_nm": round(_net_nm(track, a, b), 2),
                       "corridor": payload[0], "corridor_class": payload[1],
                       "corridor_osm_id": payload[2],
                       "min_distance_m": round(dmin, 1)})
            out.append(("IND-01", mid, ev,
                        min(1.0, (th["slow_hi_kn"] - med) / th["slow_hi_kn"]
                            * (1.0 - dmin / th["corridor_near_m"]) * 2.0)))
            break  # una alerta por ventana maximal; no se inunda el mapa
    return out


def ind02_cog_hdg_bias(track, th, counters=None):
    """P4 del CTO: sesgo unilateral de COG-HDG, no divergencia instantanea.

    Se mide el angulo CON SIGNO (proa menos rumbo sobre el fondo, normalizado a
    [-180, 180]) y se exige que mantenga el MISMO signo durante toda la ventana.
    Un buque que arrastra algo por una banda guina siempre hacia el mismo lado;
    la deriva por viento y corriente cambia de signo cuando rota el viento.
    Un umbral absoluto de 20 grados instantaneo dispara sobre el 4,12 % de los
    fixes en movimiento y es inusable como alarma (02_cto.md A.3).
    """
    out = []
    for i0, i1 in _windows(track, th["divergence_window_s"], th["max_gap_s"]):
        for a, b in _sub(track, i0, i1, th["divergence_window_s"]):
            seg = track[a:b + 1]
            vals = [_signed_diff(f["heading"], f["cog"]) for f in seg
                    if f["heading"] is not None and f["cog"] is not None
                    and f["sog"] is not None and f["sog"] >= th["divergence_min_sog_kn"]]
            if len(vals) < 3 or len(vals) < 0.7 * len(seg):
                continue
            pos = sum(1 for v in vals if v > 0)
            neg = len(vals) - pos
            frac = max(pos, neg) / len(vals)
            if frac < th["divergence_sign_frac"]:
                _bump(counters, "sign_flip_suppressed_IND-02",
                      _mid(track, a, b) if (counters or {}).get(
                          "sign_flip_suppressed_IND-02", 0) % 50 == 0 else None,
                      {"sampled": "1 de cada 50"})
                continue
            med = statistics.median(vals)
            if abs(med) < th["divergence_median_deg"]:
                continue
            absmed = abs(med)
            implausible = absmed > th["divergence_max_plausible_deg"]
            ev = _evidence(track, a, b)
            ev.update({"bias_median_deg": round(med, 1),
                       "bias_abs_median_deg": round(absmed, 1),
                       "bias_sign": "estribor" if med > 0 else "babor",
                       "sign_consistency": round(frac, 3),
                       "samples": len(vals),
                       "bias_smallest_deg": round(min(vals, key=abs), 1),
                       "bias_largest_deg": round(max(vals, key=abs), 1),
                       "interpretation": ("sensor de proa incoherente o marcha "
                                          "atras, no angulo de deriva")
                                         if implausible else
                                         "sesgo unilateral compatible con carga "
                                         "lateral sostenida",
                       "implausible_as_drift": implausible,
                       "metocean_conditioned": False,
                       "metocean_note": ("P5 del CTO (invariancia del signo frente "
                                         "al viento) NO implementado: exige "
                                         "ERA5/CMEMS. Sin el, este indicador no "
                                         "distingue arrastre de deriva por viento "
                                         "sostenido")})
            score = min(1.0, absmed / 45.0) * (0.5 if implausible else 1.0)
            out.append(("IND-02", _mid(track, a, b), ev, score))
            break
    return out


def ind03_loitering(track, th, port_mask=None, counters=None, coast_idx=None):
    out = []
    for i0, i1 in _windows(track, th["loiter_window_s"], th["max_gap_s"]):
        for a, b in _sub(track, i0, i1, th["loiter_window_s"]):
            seg = track[a:b + 1]
            sogs = [f["sog"] for f in seg if f["sog"] is not None]
            if len(sogs) < 3 or max(sogs) >= th["loiter_max_sog_kn"]:
                continue
            if any(f["navStat"] in (1, 5) for f in seg):
                continue
            if _net_nm(track, a, b) > th["loiter_max_net_nm"]:
                continue
            m = _mid(track, a, b)
            hit = port_mask.hit(m["lon"], m["lat"]) if port_mask else None
            if hit:
                _bump(counters, "port_mask_suppressed_IND-03", m, {"mask": hit})
                break
            if coast_idx is not None:
                dc, _ = coast_idx.nearest(m["lon"], m["lat"])
                if dc is not None and dc < th["min_coast_dist_m"]:
                    _bump(counters, "near_coast_suppressed_IND-03", m)
                    break
            ev = _evidence(track, a, b)
            ev.update({"sog_max_kn": max(sogs),
                       "net_displacement_nm": round(_net_nm(track, a, b), 3),
                       "port_mask_hit": None})
            out.append(("IND-03", m, ev,
                        min(1.0, ev["duration_s"] / (4 * th["loiter_window_s"]))))
            break
    return out


def ind04_ais_gap(track, th, coverage, dataset_end_ms, aoi=None, counters=None):
    """T2: solo huecos íntegramente contenidos en una ventana de cobertura."""
    out = []
    for i in range(len(track) - 1):
        dt = (track[i + 1]["ts"] - track[i]["ts"]) / 1000.0
        if dt < th["gap_s"]:
            continue
        t0, t1 = track[i]["ts"], track[i + 1]["ts"]
        if not any(w[0] <= t0 and t1 <= w[1] for w in coverage):
            continue
        ev = _evidence(track, i, i + 1)
        ev.update({"gap_s": round(dt, 1), "gap_min": round(dt / 60.0, 1),
                   "gap_state": "closed",
                   "resume_lon": track[i + 1]["lon"], "resume_lat": track[i + 1]["lat"],
                   "jump_nm": round(_net_nm(track, i, i + 1), 2)})
        out.append(("IND-04", track[i], ev, min(1.0, dt / (6 * th["gap_s"]))))

    # hueco abierto: último fix antiguo pero el grabador seguía escuchando
    last = track[-1]
    edge_m = None
    if aoi:
        edge_m = min(
            (last["lon"] - aoi[0]) * geo.m_per_deg_lon(last["lat"]),
            (aoi[2] - last["lon"]) * geo.m_per_deg_lon(last["lat"]),
            (last["lat"] - aoi[1]) * geo.M_PER_DEG_LAT,
            (aoi[3] - last["lat"]) * geo.M_PER_DEG_LAT)
    tail = (dataset_end_ms - last["ts"]) / 1000.0
    if tail >= th["gap_s"] and any(w[0] <= last["ts"] and dataset_end_ms <= w[1] + 120_000
                                   for w in coverage):
        ev = _evidence(track, len(track) - 1, len(track) - 1)
        left_aoi = edge_m is not None and edge_m < th["aoi_edge_margin_m"]
        if left_aoi:
            _bump(counters, "aoi_edge_downgraded_IND-04", track[-1],
                  {"distance_to_aoi_edge_m": round(edge_m, 1) if edge_m else None})
        ev.update({"gap_s": round(tail, 1), "gap_min": round(tail / 60.0, 1),
                   "gap_state": "open",
                   "distance_to_aoi_edge_m": round(edge_m, 1) if edge_m is not None else None,
                   "likely_left_aoi": left_aoi,
                   "note": ("el último fix está a menos de 5 NM del borde del AOI: "
                            "lo más probable es que haya salido del recorte, no "
                            "que haya callado") if left_aoi else
                           ("sigue mudo al cierre del registro; indistinguible de "
                            "salida del alcance VHF costero")})
        cap = 0.15 if left_aoi else 0.5
        out.append(("IND-04", last, ev, min(cap, tail / (12 * th["gap_s"]))))
    return out


# ITU-R M.1371, mensajes 1/2/3: el campo SOG son 10 bits en pasos de 0,1 kn.
# 1023 = «no disponible»; 1022 = 102,2 kn = «102,2 nudos o mas», o sea
# saturado. En el Baltico nada navega a 102 nudos, asi que ese valor marca un
# mensaje roto. Medido en el almacen: 1.456 fixes de 508.261 lo llevan.
SOG_SENTINEL_KN = 102.2


def ind07_impossible_jump(track, th, counters=None):
    """IND-07: el buque aparece donde no ha podido llegar.

    Dos posiciones consecutivas implican una velocidad sobre el fondo que
    ningun casco de este trafico alcanza. No es «iba rapido»: es que la
    trayectoria es fisicamente imposible.

    NO SE AFIRMA LA INTENCION, PORQUE EL AIS NO LA TRANSPORTA. Lo que si se
    puede afirmar es la EVIDENCIA, y la evidencia separa tres casos que no
    merecen el mismo trato (ver la clasificacion mas abajo).

    Que lo causa, de mas a menos probable:
      1. COLISION DE MMSI. Dos buques distintos emitiendo el mismo
         identificador. Frecuente en flota fluvial y de remolcadores. La traza
         resultante salta entre dos barcos reales.
      2. SUPLANTACION. Alguien emite una posicion falsa, a proposito. Es la
         tecnica que importa en un producto de defensa.
      3. ERROR DE DECODIFICACION o de la propia estacion receptora.
      4. Fallo nuestro de deduplicacion. Se descarta midiendo: el grabador
         deduplica por (mmsi, timestamp) y estos saltos tienen marcas de
         tiempo distintas y separadas.

    Medido sobre el almacen el 2026-11-11: 1.779 saltos en 28 MMSI de 1.253
    trazas. El peor implica 10.420 nudos, 160 km en 30 segundos. Diez de los
    28 son rusos, y entre el resto hay banderas de conveniencia y un buque
    sancionado. La herramienta no dice cual de las cuatro causas es: dice que
    la traza no puede creerse tal cual y pone los dos extremos en el mapa.
    """
    out = []
    for i in range(len(track) - 1):
        a, b = track[i], track[i + 1]
        dt = (b["ts"] - a["ts"]) / 1000.0
        if dt < th["impossible_min_dt_s"]:
            continue
        d = geo.haversine_m(a["lon"], a["lat"], b["lon"], b["lat"])
        if d < th["impossible_min_dist_m"]:
            _bump(counters, "below_min_jump_IND-07", a, {"distance_m": round(d, 1)})
            continue
        kn = (d / dt) * 1.9438445
        if kn <= th["impossible_kn"]:
            continue
        ev = _evidence(track, i, i + 1)
        ev.update({
            "implied_speed_kn": round(kn, 1),
            "jump_distance_km": round(d / 1000.0, 2),
            "elapsed_s": round(dt, 1),
            "from_lon": a["lon"], "from_lat": a["lat"],
            "to_lon": b["lon"], "to_lat": b["lat"],
            "reported_sog_kn": a.get("sog"),
            "plausible_ceiling_kn": th["impossible_kn"],
            "times_over_ceiling": round(kn / th["impossible_kn"], 1),
            "means": ("La posicion no puede creerse tal cual. Las causas posibles "
                      "son colision de MMSI, suplantacion deliberada, error de "
                      "decodificacion o un fallo del receptor. Esta herramienta "
                      "no distingue cual: senala que la traza es imposible."),
        })
        out.append((kn, a, ev))

    if not out:
        return []

    # ------------------------------------------------- de que tipo es esto
    #
    # Hasta aqui solo sabemos que la traza es imposible. La pregunta util es
    # otra: QUIEN la hizo imposible. No se puede responder con intencion --el
    # AIS no transporta causalidad-- pero SI se puede responder con evidencia,
    # y la evidencia separa tres casos que no merecen el mismo trato.
    #
    # Medido sobre el almacen del 2026-11-13, 23 MMSI y 1.547 saltos:
    #
    #   A  identificador compartido   15 MMSI   1.537 saltos   99,4 %
    #   B  mensaje mal formado         1 MMSI       2 saltos    0,1 %
    #   C  salto unico y coherente     7 MMSI       8 saltos    0,5 %
    #
    # O sea: por volumen, IND-07 es casi entero un problema de calidad de
    # dato. Emitir los tres como la misma alerta «Extrema» hacia que un
    # remolcador que comparte matricula puntuara como un incidente.
    jumps_i = [track.index(a) if a in track else -1 for _, a, _ in out]
    pings = sum(1 for p, q in zip(jumps_i, jumps_i[1:])
                if q - p <= 3 and p >= 0 and q >= 0)
    ping_ratio = pings / max(1, len(out) - 1) if len(out) > 1 else 0.0

    # ITU-R M.1371: el campo SOG son 10 bits en pasos de 0,1 kn. 1023 es «no
    # disponible» y 1022 (102,2 kn) es «102,2 o mas», o sea saturado. Ningun
    # casco del Baltico navega a 102 nudos: si el propio mensaje lo dice, el
    # mensaje esta roto y la posicion que lo acompana no vale nada.
    sogs = [p.get("sog") for p in track if p.get("sog") is not None]
    sat = sum(1 for v in sogs if v >= SOG_SENTINEL_KN) / max(1, len(sogs))

    if ping_ratio >= 0.5:
        kind, why = "shared_identifier", (
            "La traza va y vuelve entre dos zonas: %d de %d saltos tienen su "
            "vuelta a menos de tres fixes. Eso no es un buque teletransportado, "
            "son DOS emisores usando el mismo MMSI. Es un hecho sobre el "
            "identificador, no sobre un barco."
            % (pings, max(1, len(out) - 1)))
    elif sat > 0.02:
        kind, why = "malformed", (
            "El %.1f %% de los fixes de esta traza declaran SOG saturado "
            "(>= %.1f kn, el tope del campo en ITU-R M.1371). El transpondedor "
            "o el decodificador estan produciendo basura, asi que la posicion "
            "tampoco se puede creer." % (100 * sat, SOG_SENTINEL_KN))
    else:
        kind, why = "unexplained", (
            "Salto unico sobre una traza por lo demas coherente, con el campo "
            "de velocidad dentro de rango. No hay firma de identificador "
            "compartido ni de mensaje roto. Es el unico de los tres casos que "
            "merece que alguien lo mire.")

    # UNA alerta por buque, no una por salto. Un MMSI compartido produce
    # cientos de saltos -- medido: 979 en un solo remolcador -- y emitirlos
    # todos ahoga la lista sin anyadir informacion: lo que importa es que ESTE
    # identificador no se puede creer, no cada vez que lo demuestra.
    out.sort(key=lambda x: -x[0])
    kn, a, ev = out[0]
    ev["jumps_in_track"] = len(out)
    if len(out) > 1:
        ev["other_jumps_kn"] = [round(x[0], 1) for x in out[1:6]]
        ev["means"] += (" Esta traza acumula %d saltos imposibles, no uno: el "
                        "identificador entero es poco fiable." % len(out))
    ev["jump_kind"] = kind
    ev["jump_kind_why"] = why
    ev["ping_pong_ratio"] = round(ping_ratio, 2)
    ev["sog_saturated_frac"] = round(sat, 4)

    score = min(1.0, math.log10(max(1.0, kn / th["impossible_kn"])))
    # Repetirlo muchas veces refuerza que no es un fix suelto corrupto.
    if len(out) >= 5:
        score = min(1.0, score + 0.15)
    # Un identificador compartido o un mensaje roto NO son un incidente. Se
    # siguen emitiendo --saber que un MMSI no es unico cambia como se lee todo
    # lo demas que venga de el-- pero como contexto, no como alerta. Antes un
    # remolcador con la matricula duplicada puntuaba «Extrema».
    if kind in ("shared_identifier", "malformed"):
        score *= 0.25
    return [("IND-07", a, ev, score)]


def ind05_corridor_depth(track, corridor_idx, depth_grid, th, port_mask=None,
                         counters=None):
    best = None
    for i, f in enumerate(track):
        d, payload = corridor_idx.nearest(f["lon"], f["lat"])
        if d is None or d > th["corridor_close_m"]:
            continue
        depth = depth_grid.depth_at(f["lon"], f["lat"]) if depth_grid else None
        if depth is None:
            continue
        if not (th["anchor_min_depth_m"] <= depth <= th["anchor_max_depth_m"]):
            _bump(counters, "depth_band_suppressed_IND-05",
                  f if (counters or {}).get("depth_band_suppressed_IND-05", 0) % 20 == 0 else None,
                  {"depth_m": depth, "sampled": "1 de cada 20"})
            continue
        if port_mask is not None and port_mask.hit(f["lon"], f["lat"]):
            _bump(counters, "port_mask_suppressed_IND-05", f)
            continue
        w_d = 1.0 - d / th["corridor_close_m"]
        w_z = 1.0 - depth / th["anchor_max_depth_m"]
        score = max(0.0, w_d) * (0.5 + 0.5 * max(0.0, w_z))
        if best is None or score > best[3]:
            ev = _evidence(track, i, i)
            ev.update({"corridor": payload[0], "corridor_class": payload[1],
                       "corridor_osm_id": payload[2],
                       "min_distance_m": round(d, 1), "depth_m": depth,
                       "within_500m_buffer": bool(d <= th["corridor_buffer_m"]),
                       "anchor_feasible": True})
            best = ("IND-05", f, ev, score)
    return [best] if best else []


def ind06_encounters(tracks, th, port_mask=None, vessels=None, counters=None,
                     coast_idx=None):
    """P8: encuentros barco a barco. Opera sobre TODAS las trazas, no sobre una.

    Indexa los fixes por (cubo de tiempo, celda espacial) y solo compara pares
    que coinciden en el mismo cubo. Evita el O(n^2) sobre 500 buques sin
    renunciar a ningún par real: el radio de interés (500 m) es muy inferior al
    lado de la celda (0,01 deg ~ 1,1 km), así que se consultan las 9 celdas del
    entorno.
    """
    bin_ms = th["encounter_bin_s"] * 1000
    cell = 0.01
    buckets = {}
    for mmsi, tr in tracks.items():
        for f in tr:
            if f["sog"] is None or f["sog"] >= th["encounter_max_sog_kn"]:
                continue
            if f["navStat"] in (1, 5):          # fondeado o amarrado, declarado
                continue
            key = (f["ts"] // bin_ms, int(f["lon"] / cell), int(f["lat"] / cell))
            buckets.setdefault(key, []).append(f)

    # pareja -> lista de (ts, dist_m, lon, lat)
    pairs = {}
    for (tb, cx, cy), fixes_here in buckets.items():
        cand = list(fixes_here)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                cand.extend(buckets.get((tb, cx + dx, cy + dy), ()))
        for i, a in enumerate(fixes_here):
            for b in cand:
                if b["mmsi"] <= a["mmsi"]:
                    continue
                d = geo.haversine_m(a["lon"], a["lat"], b["lon"], b["lat"])
                if d > th["encounter_max_dist_m"]:
                    continue
                pairs.setdefault((a["mmsi"], b["mmsi"]), []).append(
                    (min(a["ts"], b["ts"]), d, (a["lon"] + b["lon"]) / 2,
                     (a["lat"] + b["lat"]) / 2, a, b))

    vessels = vessels or {}
    out = []
    for (m1, m2), obs in pairs.items():
        obs.sort(key=lambda o: o[0])
        run = [obs[0]]
        best = None
        for prev, cur in zip(obs, obs[1:]):
            if cur[0] - prev[0] <= th["max_gap_s"] * 1000:
                run.append(cur)
            else:
                if best is None or (run[-1][0] - run[0][0]) > (best[-1][0] - best[0][0]):
                    best = run
                run = [cur]
        if best is None or (run[-1][0] - run[0][0]) > (best[-1][0] - best[0][0]):
            best = run
        dur = (best[-1][0] - best[0][0]) / 1000.0
        if dur < th["encounter_window_s"]:
            continue
        mid = best[len(best) // 2]
        hit = port_mask.hit(mid[2], mid[3]) if port_mask else None
        if hit:
            _bump(counters, "port_mask_suppressed_IND-06",
                  {"lon": mid[2], "lat": mid[3], "ts": mid[0]}, {"mask": hit})
            continue
        coast_d = None
        if coast_idx is not None:
            coast_d, _ = coast_idx.nearest(mid[2], mid[3])
            if coast_d is not None and coast_d < th["min_coast_dist_m"]:
                _bump(counters, "near_coast_suppressed_IND-06",
                      {"lon": mid[2], "lat": mid[3], "ts": mid[0]},
                      {"coast_dist_m": round(coast_d, 1)})
                continue
        dmin = min(o[1] for o in best)
        meta2 = vessels.get(m2) or {}
        meta1 = vessels.get(m1) or {}
        ev = {"partner_mmsi": m2, "partner_name": meta2.get("name"),
              "partner_ship_type": SHIP_TYPE.get(meta2.get("shipType")),
              "both_service_craft_declared": bool(
                  meta1.get("shipType") in SERVICE_CRAFT
                  and meta2.get("shipType") in SERVICE_CRAFT),
              "min_distance_m": round(dmin, 1),
              "median_distance_m": round(statistics.median([o[1] for o in best]), 1),
              "duration_s": round(dur, 1), "duration_min": round(dur / 60.0, 1),
              "samples": len(best),
              "t_start_ms": best[0][0], "t_end_ms": best[-1][0],
              "fix_keys": [[m1, best[0][4]["ts"]], [m2, best[0][5]["ts"]]],
              "src_files": sorted({f.get("src_file") for o in best
                                   for f in (o[4], o[5]) if f.get("src_file")}),
              "sog_max_kn": max(max(o[4]["sog"], o[5]["sog"]) for o in best),
              "coast_distance_m": round(coast_d, 1) if coast_d is not None else None,
              "port_mask_hit": None}
        fix = dict(best[len(best) // 2][4])
        fix["lon"], fix["lat"] = mid[2], mid[3]
        score = min(1.0, dur / (4 * th["encounter_window_s"])) * \
            (1.0 - dmin / th["encounter_max_dist_m"])
        out.append((m1, ("IND-06", fix, ev, max(0.05, score))))
    return out


def _finite_float(val: Any, default: float = 0.0) -> float:
    """Coerce `val` to a finite float, falling back to `default` on None or NaN/Inf."""
    if val is None:
        return default
    try:
        f = float(val)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _sanitize_forcing_output(
    w_along: Any,
    w_cross: Any,
    c_along: Any,
    c_cross: Any,
    source: str,
) -> Tuple[float, float, float, float, str]:
    """Ensure all 4 projected forcing components are finite floats."""
    return (
        _finite_float(w_along, 0.0),
        _finite_float(w_cross, 0.0),
        _finite_float(c_along, 0.0),
        _finite_float(c_cross, 0.0),
        str(source),
    )


def _resolve_step_forcing(
    forcing: Any,
    fix_dict: Dict[str, Any],
    bearing_rad: float,
) -> Tuple[float, float, float, float, str]:
    """Resolve `(wind_along, wind_cross, current_along, current_cross, forcing_source)`."""
    if forcing is None:
        return (0.0, 0.0, 0.0, 0.0, "none")
    b_rad = _finite_float(bearing_rad, 0.0)
    if callable(forcing):
        res = forcing(fix_dict, b_rad)
        if len(res) == 5:
            return _sanitize_forcing_output(res[0], res[1], res[2], res[3], str(res[4]))
        return _sanitize_forcing_output(res[0], res[1], res[2], res[3], "callable")
    if isinstance(forcing, dict):
        if "wind_along" in forcing:
            return _sanitize_forcing_output(
                forcing.get("wind_along"),
                forcing.get("wind_cross"),
                forcing.get("current_along"),
                forcing.get("current_cross"),
                str(forcing.get("source") or "provided"),
            )
        if "wind_speed_kn" in forcing or "wind_ms" in forcing:
            if "wind_speed_kn" in forcing and forcing.get("wind_speed_kn") is not None:
                w_spd = _finite_float(forcing.get("wind_speed_kn"), 0.0)
            else:
                w_spd = _finite_float(forcing.get("wind_ms"), 0.0) * 1.9438445
            w_from_raw = forcing.get("wind_from_deg")
            if w_from_raw is None:
                w_from_raw = forcing.get("wind_dir_deg")
            w_from = _finite_float(w_from_raw, 0.0)
            c_spd = _finite_float(forcing.get("current_speed_kn"), 0.0)
            c_to = _finite_float(forcing.get("current_to_deg"), 0.0)
            w_to_rad = math.radians((w_from + 180.0) % 360.0)
            c_to_rad = math.radians(c_to % 360.0)
            return _sanitize_forcing_output(
                w_spd * math.cos(w_to_rad - b_rad),
                w_spd * math.sin(w_to_rad - b_rad),
                c_spd * math.cos(c_to_rad - b_rad),
                c_spd * math.sin(c_to_rad - b_rad),
                str(forcing.get("source") or "metocean"),
            )
        ts_val = _finite_float(fix_dict.get("ts"), -1.0)
        if ts_val >= 0.0:
            hour_ts = int((int(ts_val) // 3_600_000) * 3600)
            if hour_ts in forcing and forcing[hour_ts] is not None:
                w_spd_raw, w_from_raw, c_spd_raw, c_to_raw = forcing[hour_ts]
                w_spd = _finite_float(w_spd_raw, 0.0)
                w_from = _finite_float(w_from_raw, 0.0)
                c_spd = _finite_float(c_spd_raw, 0.0)
                c_to = _finite_float(c_to_raw, 0.0)
                w_to_rad = math.radians((w_from + 180.0) % 360.0)
                c_to_rad = math.radians(c_to % 360.0)
                return _sanitize_forcing_output(
                    w_spd * math.cos(w_to_rad - b_rad),
                    w_spd * math.sin(w_to_rad - b_rad),
                    c_spd * math.cos(c_to_rad - b_rad),
                    c_spd * math.sin(c_to_rad - b_rad),
                    "hourly_lookup",
                )
    return (0.0, 0.0, 0.0, 0.0, "none")


def ind08_motion_anomaly(
    track: Sequence[Dict[str, Any]],
    th: Optional[Dict[str, Any]] = None,
    corridor_idx: Any = None,
    forcing: Any = None,
    counters: Optional[Dict[str, Any]] = None,
    weights_path: Optional[str] = None,
    port_mask: Any = None,
    vessels: Optional[Dict[Any, Any]] = None,
    ship_type: Any = None,
    depth_grid: Any = None,
    anchor_weights_path: Optional[str] = None,
) -> List[Tuple[str, Dict[str, Any], Dict[str, Any], float]]:
    """IND-08: anomalía cinemática aprendida con ShipMotionGaussianMLP (14->64->64->4).

    Evalúa transiciones consecutivas de velocidad `(v_east, v_north)` sobre pasos
    de `60 <= dt_s <= 300` con velocidad `sog` en `(2.0, 30.0)` nudos. Emite a lo
    sumo una alerta por traza (el paso con mayor `radial_z`) cuando al menos
    `motion_min_hits` pasos sufren frenada anómala (`radial_z > sqrt(chi2_{2, 0.95}) = 2.448`,
    `|Δv| >= motion_min_dv_kn` y caída longitudinal `sog_before - sog_after >= motion_min_decel_kn`)
    a `<= motion_corridor_m` de `corridor_idx`, fuera de `port_mask` y sin solapar
    saltos imposibles `IND-07`.
    Si el fichero de pesos no existe o es inválido, degrada limpiamente a `[]`.
    """
    th = th or THRESHOLDS
    model = motion.load_model_safe(weights_path)
    if model is None:
        _bump_count(counters, "model_unavailable_IND-08")
        return []

    min_dt = float(th.get("motion_min_dt_s", motion.VALID_DT_MIN_S))
    max_dt = float(th.get("motion_max_dt_s", motion.VALID_DT_MAX_S))
    min_sog = float(th.get("motion_min_sog_kn", motion.VALID_SOG_MIN_KN))
    max_sog = float(th.get("motion_max_sog_kn", motion.VALID_SOG_MAX_KN))
    z_thresh = float(th.get("motion_radial_z", motion.RADIAL_Z_95CI))
    min_dv = float(th.get("motion_min_dv_kn", 1.0))
    min_decel = float(th.get("motion_min_decel_kn", 0.8))
    min_hits = int(th.get("motion_min_hits", 2))
    max_corridor_m = float(th.get("motion_corridor_m", 5000.0))
    corridor_buf_m = float(th.get("corridor_buffer_m", 500.0))
    max_plausible_kn = float(th.get("impossible_kn", 45.0))
    imp_min_dt_s = float(th.get("impossible_min_dt_s", 5.0))
    imp_min_dist_m = float(th.get("impossible_min_dist_m", 2000.0))

    resolved_ship_type = ship_type
    if resolved_ship_type is None and track:
        for f_item in track:
            st_cand = f_item.get("shipType")
            if st_cand is None:
                st_cand = f_item.get("ship_type")
            if st_cand is not None:
                resolved_ship_type = st_cand
                break
        if resolved_ship_type is None and vessels:
            mmsi_key = track[0].get("mmsi")
            meta_v = vessels.get(mmsi_key) or vessels.get(str(mmsi_key)) or {}
            resolved_ship_type = meta_v.get("shipType")
            if resolved_ship_type is None:
                resolved_ship_type = meta_v.get("ship_type")
    is_maneuver = motion.is_maneuver_vessel_type(resolved_ship_type)

    # Pre-identify raw IND-07 impossible jump indices (including sub-60s jumps)
    jump_raw_indices = set()
    for i in range(len(track) - 1):
        fa, fb = track[i], track[i + 1]
        try:
            lon_a, lat_a, ts_a = float(fa["lon"]), float(fa["lat"]), float(fa["ts"])
            lon_b, lat_b, ts_b = float(fb["lon"]), float(fb["lat"]), float(fb["ts"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (
            math.isfinite(lon_a)
            and math.isfinite(lat_a)
            and math.isfinite(ts_a)
            and math.isfinite(lon_b)
            and math.isfinite(lat_b)
            and math.isfinite(ts_b)
        ):
            continue
        dt_raw = (ts_b - ts_a) / 1000.0
        if dt_raw < imp_min_dt_s:
            continue
        d_raw = geo.haversine_m(lon_a, lat_a, lon_b, lat_b)
        if d_raw >= imp_min_dist_m and (d_raw / dt_raw) * 1.9438445 > max_plausible_kn:
            jump_raw_indices.add(i)
            jump_raw_indices.add(i + 1)

    kept: List[Tuple[int, Dict[str, Any]]] = []
    for idx, f in enumerate(track):
        lon, lat, sog, ts = f.get("lon"), f.get("lat"), f.get("sog"), f.get("ts")
        if lon is None or lat is None or sog is None or ts is None:
            continue
        try:
            lon_val = float(lon)
            lat_val = float(lat)
            sog_val = float(sog)
            ts_val = float(ts)
        except (TypeError, ValueError):
            continue
        if not (
            math.isfinite(lon_val)
            and math.isfinite(lat_val)
            and math.isfinite(sog_val)
            and math.isfinite(ts_val)
        ):
            continue
        if f.get("navStat") in (1, 5):
            continue
        if not (min_sog < sog_val < max_sog):
            continue
        if not kept or (ts_val - float(kept[-1][1]["ts"])) / 1000.0 >= min_dt:
            kept.append((idx, f))

    if len(kept) < 3:
        return []

    two_pi = 2.0 * math.pi
    segs: List[Dict[str, Any]] = []
    for k in range(len(kept) - 1):
        idx0, f0 = kept[k]
        idx1, f1 = kept[k + 1]
        dt_s = (float(f1["ts"]) - float(f0["ts"])) / 1000.0
        sog0 = float(f0["sog"])
        sog1 = float(f1["sog"])
        in_domain = motion.check_domain(
            dt_s,
            sog1,
            min_dt_s=min_dt,
            max_dt_s=max_dt,
            min_sog_kn=min_sog,
            max_sog_kn=max_sog,
        )
        lat0, lon0 = float(f0["lat"]), float(f0["lon"])
        lat1, lon1 = float(f1["lat"]), float(f1["lon"])
        dlat_nm = (lat1 - lat0) * 60.0
        dlon_nm = (lon1 - lon0) * 60.0 * math.cos(math.radians(0.5 * (lat0 + lat1)))
        dist_nm = math.hypot(dlon_nm, dlat_nm)
        disp_sog = dist_nm / max(dt_s / 3600.0, 1e-6)
        cog_raw = f1.get("cog")
        cog_val: Optional[float] = None
        if cog_raw is not None:
            try:
                c_f = float(cog_raw)
                if math.isfinite(c_f):
                    cog_val = c_f
            except (TypeError, ValueError):
                cog_val = None
        if dist_nm < 1e-6 and cog_val is not None:
            bearing_rad = math.radians(cog_val % 360.0)
        else:
            bearing_rad = math.atan2(dlon_nm, dlat_nm) % two_pi
        v_east = sog1 * math.sin(bearing_rad)
        v_north = sog1 * math.cos(bearing_rad)
        overlaps_jump = any(
            r_idx in jump_raw_indices for r_idx in range(idx0, idx1 + 1)
        )
        segs.append(
            {
                "idx0": idx0,
                "idx1": idx1,
                "kept_idx_end": k + 1,
                "f0": f0,
                "f1": f1,
                "lon0": lon0,
                "lat0": lat0,
                "lon1": lon1,
                "lat1": lat1,
                "dt_s": dt_s,
                "sog0": sog0,
                "sog1": sog1,
                "disp_sog": disp_sog,
                "in_domain": in_domain and (disp_sog <= max_plausible_kn) and not overlaps_jump,
                "bearing_rad": bearing_rad,
                "v_east": v_east,
                "v_north": v_north,
            }
        )

    candidates: List[Tuple[float, Dict[str, Any], Dict[str, Any], float, int, float]] = []
    model_name = str(model.get("model_name", "ShipMotionGaussianMLP"))

    for j in range(len(segs) - 1):
        s_prev = segs[j]
        s_curr = segs[j + 1]
        if not (s_prev["in_domain"] and s_curr["in_domain"]):
            continue

        sog_before = float(s_prev["sog1"])
        sog_after = float(s_curr["sog1"])
        if abs(s_prev["disp_sog"] - sog_before) >= 2.5:
            continue
        if (
            s_curr["disp_sog"] > max_plausible_kn
            or s_curr["disp_sog"] > max(sog_before, sog_after) * 1.8 + 3.0
            or abs(s_curr["disp_sog"] - sog_after) >= 2.5
        ):
            continue

        v_east0 = float(s_prev["v_east"])
        v_north0 = float(s_prev["v_north"])
        b_rad = float(s_prev["bearing_rad"])

        v_east1 = float(s_curr["v_east"])
        v_north1 = float(s_curr["v_north"])
        dt_s = float(s_curr["dt_s"])

        actual_dv_east = v_east1 - v_east0
        actual_dv_north = v_north1 - v_north0
        dv_kn = math.hypot(actual_dv_east, actual_dv_north)
        if dv_kn < min_dv:
            _bump_count(counters, "below_min_dv_IND-08")
            continue
        if (sog_before - sog_after) < min_decel:
            _bump_count(counters, "non_braking_turn_IND-08")
            continue

        # Strictly causal prev_dv_east, prev_dv_north from preceding step (t0 -> t1)
        fb_dsog = max(-2.5, min(2.5, sog_before - float(s_prev["sog0"])))
        fb_prev_dve = fb_dsog * math.sin(b_rad)
        fb_prev_dvn = fb_dsog * math.cos(b_rad)
        if (
            j > 0
            and segs[j - 1]["in_domain"]
            and abs(segs[j - 1]["disp_sog"] - float(segs[j - 1]["sog1"])) < 2.5
        ):
            raw_prev_dve = v_east0 - float(segs[j - 1]["v_east"])
            raw_prev_dvn = v_north0 - float(segs[j - 1]["v_north"])
            if math.hypot(raw_prev_dve, raw_prev_dvn) < 2.5:
                prev_dv_east = raw_prev_dve
                prev_dv_north = raw_prev_dvn
            else:
                prev_dv_east = fb_prev_dve
                prev_dv_north = fb_prev_dvn
        else:
            prev_dv_east = fb_prev_dve
            prev_dv_north = fb_prev_dvn

        f_prev = s_curr["f0"]
        flow_dv_east, flow_dv_north, has_flow = motion.lookup_flow(
            f_prev["lat"], f_prev["lon"], v_east0, v_north0, model
        )
        w_along, w_cross, c_along, c_cross, f_src = _resolve_step_forcing(
            forcing, f_prev, b_rad
        )
        feat_map: Dict[str, float] = {
            "v_east": v_east0,
            "v_north": v_north0,
            "sog": sog_before,
            "dt": dt_s,
            "wind_along": w_along,
            "wind_cross": w_cross,
            "current_along": c_along,
            "current_cross": c_cross,
            "prev_dv_east": prev_dv_east,
            "prev_dv_north": prev_dv_north,
            "is_maneuver_vessel": is_maneuver,
            "flow_dv_east": flow_dv_east,
            "flow_dv_north": flow_dv_north,
            "has_flow": has_flow,
        }
        pred = motion.predict(feat_map, model_data=model)
        mu_e, mu_n, std_e, std_n = pred
        z_e, z_n, radial_z, nll, is_anom = motion.anomaly_score(
            actual_dv_east, actual_dv_north, pred, z_threshold_95ci=z_thresh
        )
        if not is_anom:
            continue

        if port_mask is not None:
            hit_pm = (
                port_mask.hit(s_curr["lon0"], s_curr["lat0"])
                or port_mask.hit(s_curr["lon1"], s_curr["lat1"])
            )
            if hit_pm:
                _bump(counters, "port_mask_suppressed_IND-08", s_curr["f1"], {"mask": hit_pm})
                continue

        idx_start = int(s_curr["idx0"])
        idx_end = int(s_curr["idx1"])
        kept_idx_end = int(s_curr["kept_idx_end"])
        f_start = s_curr["f0"]
        f_end = s_curr["f1"]

        corridor_ev: Dict[str, Any] = {}
        if corridor_idx is not None:
            dist_m, payload = corridor_idx.nearest(f_end["lon"], f_end["lat"])
            if dist_m is None or payload is None or dist_m > max_corridor_m:
                _bump(
                    counters,
                    "off_corridor_suppressed_IND-08",
                    f_end,
                    {"dist_m": round(dist_m, 1) if dist_m is not None else None},
                )
                continue
            if isinstance(payload, (tuple, list)):
                cable_name = payload[0] if len(payload) > 0 else None
                corridor_class = payload[1] if len(payload) > 1 else None
                corridor_osm_id = payload[2] if len(payload) > 2 else None
            else:
                cable_name = str(payload)
                corridor_class = None
                corridor_osm_id = None
            corridor_ev = {
                "dist_m": round(dist_m, 1),
                "min_distance_m": round(dist_m, 1),
                "corridor": cable_name,
                "corridor_class": corridor_class,
                "corridor_osm_id": corridor_osm_id,
                "within_500m_buffer": bool(dist_m <= corridor_buf_m),
            }

        ev = _evidence(track, idx_start, idx_end)
        ev.update(
            {
                "radial_z": round(radial_z, 3),
                "z_east": round(z_e, 3),
                "z_north": round(z_n, 3),
                "nll": round(nll, 4),
                "dt_s": round(dt_s, 1),
                "dv_kn": round(dv_kn, 3),
                "prev_lon": round(float(f_start["lon"]), 6),
                "prev_lat": round(float(f_start["lat"]), 6),
                "v_east_before": round(v_east0, 3),
                "v_north_before": round(v_north0, 3),
                "pred_dv_east": round(mu_e, 4),
                "pred_dv_north": round(mu_n, 4),
                "actual_dv_east": round(actual_dv_east, 4),
                "actual_dv_north": round(actual_dv_north, 4),
                "prev_dv_east": round(prev_dv_east, 4),
                "prev_dv_north": round(prev_dv_north, 4),
                "is_maneuver_vessel": round(is_maneuver, 1),
                "flow_dv_east": round(flow_dv_east, 4),
                "flow_dv_north": round(flow_dv_north, 4),
                "has_flow": bool(has_flow),
                "std_east": round(std_e, 4),
                "std_north": round(std_n, 4),
                "sog_before_kn": round(sog_before, 2),
                "sog_after_kn": round(sog_after, 2),
                "forcing_source": f_src,
                "model_name": model_name,
                "window": {
                    "t_start_ms": f_start["ts"],
                    "t_end_ms": f_end["ts"],
                    "dt_s": round(dt_s, 1),
                },
            }
        )
        if corridor_ev:
            ev.update(corridor_ev)
        score = min(1.0, radial_z / (2.0 * z_thresh))
        candidates.append((radial_z, f_end, ev, score, kept_idx_end, max(0.0, sog_before - sog_after)))

    if len(candidates) < min_hits:
        return []

    candidates.sort(key=lambda item: -item[0])
    peak_rz, peak_fix, peak_ev, peak_score, peak_kept_idx, peak_braking_kn = candidates[0]
    peak_ev["anomaly_steps_in_track"] = len(candidates)

    tier2_model = motion.load_anchor_tier2_safe(anchor_weights_path)
    if tier2_model is not None:
        lo = max(0, peak_kept_idx - 3)
        hi = min(len(kept), peak_kept_idx + 4)
        crab_diffs: List[float] = []
        for _, w_fix in kept[lo:hi]:
            hdg_raw = w_fix.get("heading")
            cog_raw = w_fix.get("cog")
            if hdg_raw is None or cog_raw is None:
                continue
            try:
                h_val = float(hdg_raw)
                c_val = float(cog_raw)
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(h_val) and math.isfinite(c_val)):
                continue
            if h_val < 0.0 or h_val >= 360.0 or c_val < 0.0 or c_val >= 360.0:
                continue
            crab_diffs.append(_signed_diff(h_val, c_val))

        if crab_diffs:
            crab_deg: Optional[float] = float(statistics.median(abs(d) for d in crab_diffs))
            pos_cnt = sum(1 for d in crab_diffs if d > 0.0)
            neg_cnt = sum(1 for d in crab_diffs if d < 0.0)
            crab_sign_consistency = max(pos_cnt, neg_cnt) / float(len(crab_diffs))
        else:
            crab_deg = None
            crab_sign_consistency = 0.0

        depth_m: Optional[float] = None
        if depth_grid is not None:
            raw_depth = None
            if hasattr(depth_grid, "sample"):
                raw_depth = depth_grid.sample(peak_fix["lon"], peak_fix["lat"])
            elif hasattr(depth_grid, "depth_at"):
                raw_depth = depth_grid.depth_at(peak_fix["lon"], peak_fix["lat"])
            if raw_depth is not None:
                try:
                    d_val = float(raw_depth)
                    if math.isfinite(d_val):
                        depth_m = d_val
                except (TypeError, ValueError):
                    depth_m = None

        if depth_m is None:
            seabed_reachable = 0.5
        elif 10.0 <= depth_m <= 110.0:
            seabed_reachable = 1.0
        elif 110.0 < depth_m <= 120.0:
            seabed_reachable = (120.0 - depth_m) / 10.0
        else:
            seabed_reachable = 0.0

        t2_feats = {
            "peak_radial_z_capped": min(float(peak_rz), 50.0),
            "braking_kn": float(peak_braking_kn),
            "unilateral_crab_deg": crab_deg if crab_deg is not None else 0.0,
            "crab_sign_consistency": crab_sign_consistency,
            "seabed_reachable": seabed_reachable,
        }
        t2_prob, t2_band = motion.score_anchor_drag(t2_feats, tier2_model)
        peak_ev["anchor_drag_prob"] = round(t2_prob, 3)
        peak_ev["anchor_drag_band"] = t2_band
        peak_ev["anchor_drag_crab_deg"] = round(crab_deg, 1) if crab_deg is not None else None
        peak_ev["anchor_drag_depth_m"] = round(depth_m, 1) if depth_m is not None else None
        peak_ev["anchor_drag_source"] = "physics-sim-tier2"

    return [("IND-08", peak_fix, peak_ev, peak_score)]


# ------------------------------------------------------------------- motor

def run(tracks, corridor_idx, depth_grid, coverage, dataset_end_ms,
        port_mask=None, th=None, vessels=None, enabled=None, coast_idx=None,
        aoi=None, forcing=None):
    """Devuelve (alerts, stats). alerts = lista de dicts listos para GeoJSON."""
    th = th or THRESHOLDS
    enabled = enabled or set(JUSTIFICATION)
    vessels = vessels or {}
    alerts = []
    st = {"tracks": len(tracks), "by_indicator": {k: 0 for k in JUSTIFICATION},
          "tracks_with_alert": 0, "port_mask_suppressed": 0,
          "eligible_tracks": {}}

    # trazabilidad del tamaño de muestra: cuántas trazas pueden siquiera
    # activar cada indicador dado su requisito de duración de ventana.
    for key, span in (("IND-01", th["slow_window_s"]), ("IND-02", th["divergence_window_s"]),
                      ("IND-03", th["loiter_window_s"])):
        st["eligible_tracks"][key] = sum(
            1 for t in tracks.values() if _windows(t, span, th["max_gap_s"]))
    st["eligible_tracks"]["IND-08"] = sum(
        1 for t in tracks.values() if len(t) >= 3
    )

    # IND-06 es por PAREJAS: se calcula una vez sobre todo el conjunto y se
    # reparte por buque antes del bucle.
    pairwise = {}
    if "IND-06" in enabled:
        for mmsi, hit in ind06_encounters(tracks, th, port_mask=port_mask,
                                          vessels=vessels, counters=st,
                                          coast_idx=coast_idx):
            pairwise.setdefault(mmsi, []).append(hit)

    for mmsi, track in tracks.items():
        meta = vessels.get(mmsi, {})
        hits = list(pairwise.get(mmsi, ()))
        if "IND-01" in enabled:
            hits += ind01_slow_on_corridor(track, corridor_idx, th,
                                           depth_grid=depth_grid,
                                           port_mask=port_mask, counters=st)
        if "IND-02" in enabled:
            hits += ind02_cog_hdg_bias(track, th, counters=st)
        if "IND-03" in enabled:
            hits += ind03_loitering(track, th, port_mask, counters=st,
                                    coast_idx=coast_idx)
        if "IND-04" in enabled:
            hits += ind04_ais_gap(track, th, coverage, dataset_end_ms,
                                  aoi=aoi, counters=st)
        if "IND-07" in enabled:
            hits += ind07_impossible_jump(track, th, counters=st)
        if "IND-05" in enabled:
            hits += ind05_corridor_depth(track, corridor_idx, depth_grid, th,
                                         port_mask=port_mask, counters=st)
        if "IND-08" in enabled:
            hits += ind08_motion_anomaly(track, th, corridor_idx=corridor_idx,
                                         forcing=forcing, counters=st,
                                         port_mask=port_mask, vessels=vessels,
                                         ship_type=meta.get("shipType"),
                                         depth_grid=depth_grid)
        if not hits:
            continue
        st["tracks_with_alert"] += 1
        composite = sum(th["weights"].get(k, 0.0) * min(1.0, max(0.0, s))
                        for k, _, _, s in hits)
        for key, fix, ev, score in hits:
            st["by_indicator"][key] += 1
            alerts.append({
                "kind": "exposure" if key in th.get("exposure_only", ()) else "alert",
                "mmsi": mmsi,
                "name": meta.get("name") or None,
                "ship_type": meta.get("shipType"),
                "ship_type_text": SHIP_TYPE.get(meta.get("shipType")),
                "service_craft_declared": meta.get("shipType") in SERVICE_CRAFT,
                "imo": meta.get("imo") or None,
                "call_sign": meta.get("callSign") or None,
                "destination": meta.get("destination") or None,
                "draught_m": meta.get("draught_m"),
                "indicator": key,
                "score": round(min(1.0, max(0.0, score)), 3),
                "composite_score": round(min(1.0, composite), 3),
                "lon": fix["lon"], "lat": fix["lat"],
                "ts_ms": fix["ts"],
                "navStat": fix["navStat"],
                "sog_kn": fix["sog"], "cog_deg": fix["cog"],
                "heading_deg": fix["heading"],
                "evidence": ev,
            })
    alerts.sort(key=lambda a: (a["kind"] != "alert", -a["composite_score"], a["mmsi"]))
    st["alerts"] = sum(1 for a in alerts if a["kind"] == "alert")
    st["exposures"] = sum(1 for a in alerts if a["kind"] == "exposure")
    return alerts, st


def thresholds_sha(th=None):
    """Huella del juego de umbrales. Regla de diseño de 02_cto.md E.3: en un
    expediente probatorio hay que poder decir CON QUÉ umbrales se calculó, no
    solo que hubo alerta."""
    blob = json.dumps(th or THRESHOLDS, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def to_geojson(alerts, provenance=None):
    sha = thresholds_sha()
    for a in alerts:
        a.setdefault("provenance", {})["thresholds_sha256_16"] = sha
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature",
                          "geometry": {"type": "Point", "coordinates": [a["lon"], a["lat"]]},
                          "properties": a} for a in alerts],
            "properties": {"thresholds": THRESHOLDS,
                           "thresholds_sha256_16": sha,
                           "justification": JUSTIFICATION,
                           "cto_mapping": CTO_MAPPING,
                           "provenance": provenance or {},
                           "calibrated": False}}
