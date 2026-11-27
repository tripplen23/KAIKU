/* explain.js - plain-language content so every alert explains itself.
 * Three layers per indicator: what it is, why this one fired, what it does NOT
 * prove. The last one is not optional: it is the honest part. */
'use strict';

var EXPLAIN = {
  'IND-01': {
    en: { title: 'Slow and steady over a cable',
      what: 'The vessel held a speed between 1 and 5 knots for at least 30 minutes while sitting on top of a subsea cable or pipeline corridor.',
      why: 'That speed band is the one a ship moves at when it is dragging an anchor along the seabed. Normal transit is faster; a vessel at anchor is slower.',
      not: 'It proves nothing on its own. Survey ships, tugs, pilots, fishing vessels and naval units protecting the cable all move exactly like this. In this very dataset two allied warships triggered this indicator while guarding the infrastructure.',
      tech: 'P3 (drag band 1.0-5.0 kn sustained >=30 min) AND P2 (corridor proximity), gated by depth from the EMODnet DTM and suppressed inside the port/anchorage mask.' },
    es: { title: 'Lento y sostenido sobre un cable',
      what: 'El buque mantuvo entre 1 y 5 nudos durante al menos 30 minutos justo encima de un corredor de cable o gasoducto submarino.',
      why: 'Es la banda de velocidad a la que se mueve un barco que arrastra un ancla por el fondo. El tránsito normal es más rápido; un buque fondeado, más lento.',
      not: 'Por sí solo no prueba nada. Buques de reconocimiento, remolcadores, prácticos, pesqueros y unidades navales que protegen el cable se mueven exactamente así. En este mismo conjunto de datos, dos buques de guerra aliados dispararon este indicador mientras vigilaban la infraestructura.',
      tech: 'P3 (banda de arrastre 1,0-5,0 kn sostenida >=30 min) Y P2 (proximidad a corredor), condicionado por profundidad del DTM de EMODnet y suprimido dentro de la máscara de puertos y fondeaderos.' }
  },
  'IND-02': {
    en: { title: 'Crabbing: pointing one way, moving another',
      what: 'The direction the bow points (heading) and the direction the ship actually travels (course over ground) disagreed consistently, always to the same side.',
      why: 'Something is pulling the ship off its heading. A dragged anchor on an off-centre hawse applies a steady turning moment to one side. Wind and current also do this, but they change side as they rotate.',
      not: 'Wind, current and a crosswise rudder trim produce the same picture. The signature here is the persistence of the SIGN, not the size of the angle. Absolute thresholds are useless: a plain >20 degrees rule fires on about 3% of all moving fixes.',
      tech: 'P4 (signed one-sided COG-HDG bias). The sign-flip test suppressed 1,555 episodes and emitted 9. Heading is absent in 12.6% of fixes, so this indicator cannot see every vessel.' },
    es: { title: 'Apuntando a un lado y navegando a otro',
      what: 'La dirección a la que apunta la proa y la dirección en la que el buque realmente avanza discreparon de forma sostenida, siempre hacia el mismo lado.',
      why: 'Algo tira del buque fuera de su rumbo. Un ancla arrastrada por un escobén descentrado aplica un momento de giro constante hacia un lado. El viento y la corriente también, pero cambian de lado al rotar.',
      not: 'El viento, la corriente y un timón descompensado producen la misma imagen. La firma es la persistencia del SIGNO, no el tamaño del ángulo. Los umbrales absolutos son inútiles: una regla de >20 grados dispara sobre el 3% de todos los fixes en movimiento.',
      tech: 'P4 (sesgo unilateral con signo de COG-HDG). El test de cambio de signo suprimió 1.555 episodios y emitió 9. El rumbo de proa falta en el 12,6% de los fixes.' }
  },
  'IND-03': {
    en: { title: 'Loitering',
      what: 'The vessel stayed inside a small area for a long time instead of passing through.',
      why: 'Staying put over infrastructure can mean work is being done on it, or that someone is looking at it.',
      not: 'Almost always harmless, which is why this is an EXPOSURE and not an alert. Of ten cases measured, eight were pilot boats on station and two were test transponders named FURUNOP and NAVI TEST that moved three or four metres in an hour.',
      tech: 'Radius and dwell thresholds, suppressed near the coast. Closest CTO item is P8 (at-sea encounter). Downgraded to exposure by measurement, not by opinion.' },
    es: { title: 'Merodeo',
      what: 'El buque permaneció dentro de un área pequeña mucho tiempo en lugar de pasar de largo.',
      why: 'Quedarse quieto encima de infraestructura puede significar que se está trabajando en ella, o que alguien la está mirando.',
      not: 'Casi siempre inofensivo, y por eso es EXPOSICIÓN y no alerta. De diez casos medidos, ocho eran lanchas de prácticos en estación y dos eran transpondedores de prueba llamados FURUNOP y NAVI TEST que se movieron tres o cuatro metros en una hora.',
      tech: 'Umbrales de radio y permanencia, suprimidos cerca de la costa. Lo más próximo del CTO es P8 (encuentro en el mar). Degradado a exposición por medición, no por opinión.' }
  },
  'IND-04': {
    en: { title: 'The vessel stopped reporting',
      what: 'The stream of AIS positions from this vessel had a gap longer than expected.',
      why: 'AIS is a self-reported broadcast. Switching it off is the cheapest way to disappear, and it is a known tactic.',
      not: 'A gap in OUR data is not a gap in the vessel transmission. Coverage, antenna shadow, and our own recorder stopping all look identical from here. Three of ten early candidates turned out to be artefacts of the recorder being stopped: that is a 30% false positive rate from our own downtime.',
      tech: 'P6 (AIS gap corrected for coverage). Gaps are only counted inside measured recorder uptime; gaps at the AOI edge are downgraded, because leaving the box is not going dark.' },
    es: { title: 'El buque dejó de emitir',
      what: 'El flujo de posiciones AIS de este buque tuvo un hueco mayor de lo esperado.',
      why: 'El AIS es una emisión autodeclarada. Apagarlo es la forma más barata de desaparecer, y es una táctica conocida.',
      not: 'Un hueco en NUESTROS datos no es un hueco en la emisión del buque. La cobertura, la sombra de antena y la parada de nuestro propio grabador se ven igual desde aquí. Tres de diez candidatos iniciales resultaron artefactos de la parada del grabador: un 30% de falsos positivos generados por nuestra propia indisponibilidad.',
      tech: 'P6 (hueco de AIS corregido por cobertura). Solo se cuentan huecos dentro del tiempo de actividad medido; los del borde del AOI se degradan, porque salir de la caja no es apagarse.' }
  },
  'IND-05': {
    en: { title: 'Close to infrastructure',
      what: 'The vessel passed within one nautical mile of a cable or pipeline, weighted by how shallow the water is.',
      why: 'An anchor can only reach the seabed where the water is shallow enough. Proximity plus shallow water is where the physical risk lives.',
      not: 'This is pure geography, not behaviour. The Gulf of Finland is crossed by cables, so every ferry crosses one several times a day: 71 of the first 75 cases were exactly that. It is shown as EXPOSURE to give context, never as an accusation.',
      tech: 'P2 (buffer to cable axis, 1 NM with a 500 m inner tier) combined with the depth gate. Exposure only, by design.' },
    es: { title: 'Cerca de la infraestructura',
      what: 'El buque pasó a menos de una milla náutica de un cable o gasoducto, ponderado por lo somero que es el agua.',
      why: 'Un ancla solo alcanza el fondo donde el agua es bastante somera. Proximidad más poca profundidad es donde vive el riesgo físico.',
      not: 'Esto es pura geografía, no comportamiento. El golfo de Finlandia está cruzado por cables, así que cada ferry cruza varios al día: 71 de los primeros 75 casos eran exactamente eso. Se muestra como EXPOSICIÓN para dar contexto, nunca como acusación.',
      tech: 'P2 (buffer al eje del cable, 1 NM con tier interior de 500 m) combinado con la condición de profundidad. Solo exposición, por diseño.' }
  },
  'IND-06': {
    en: { title: 'Two vessels met at sea',
      what: 'Two ships were close to each other, slowly, away from a port.',
      why: 'Ship-to-ship transfer away from port is how sanctioned cargo changes hands, and it is a standard sanctions-evasion indicator.',
      not: 'Pilots boarding, tugs assisting and bunkering all look the same. All 15 measured cases were pilot boats alongside. The OSM port mask alone is not enough to filter them. EXPOSURE, not alert.',
      tech: 'P8 (at-sea encounter), equivalent to the EMSA AtSeaEncounter. Downgraded after measuring 61 candidates.' },
    es: { title: 'Dos buques se encontraron en el mar',
      what: 'Dos barcos estuvieron cerca el uno del otro, despacio, lejos de un puerto.',
      why: 'La transferencia barco a barco fuera de puerto es como cambia de manos la carga sancionada, y es un indicador estándar de evasión de sanciones.',
      not: 'Prácticos embarcando, remolcadores asistiendo y repostajes se ven igual. Los 15 casos medidos eran lanchas de prácticos al costado. La máscara de puertos de OSM por sí sola no basta. EXPOSICIÓN, no alerta.',
      tech: 'P8 (encuentro en el mar), equivalente al AtSeaEncounter de EMSA. Degradado tras medir 61 candidatos.' }
  },
  'IND-07': {
    en: { title: 'The vessel appeared where it could not have got to',
      what: 'Two consecutive positions imply a speed over ground no hull in this traffic can reach. Not "it was going fast" — the track is physically impossible.',
      why: 'Forty-five knots is the practical ceiling for merchants, tankers, tugs and ferries. Above it, something about the broadcast is wrong, and finding out what is the point.',
      not: 'It does NOT say which of four things happened, and the tool will not pretend otherwise: an MMSI collision (two real vessels sharing one identifier, common in river and tug fleets), deliberate spoofing, a decoding error, or a fault at the receiving station. Detection is arithmetic; cause is not.',
      tech: 'Measured on the store 2026-11-11: 1,779 jumps across 28 MMSI of 1,253 tracks. Worst case 10,420 kn — 160 km in 30 s. Ten of the 28 are Russian-flagged, the rest are mostly flags of convenience, and one is on the OFAC sanctions list. Jumps under 2 km or under 5 s are ignored as GPS noise.' },
    es: { title: 'El buque aparece donde no ha podido llegar',
      what: 'Dos posiciones consecutivas implican una velocidad sobre el fondo que ningún casco de este tráfico alcanza. No es que «iba rápido»: la trayectoria es físicamente imposible.',
      why: 'Cuarenta y cinco nudos es el techo práctico de mercantes, petroleros, remolcadores y ferris. Por encima, algo va mal en la emisión, y averiguar el qué es el objetivo.',
      not: 'NO dice cuál de cuatro cosas ocurrió, y la herramienta no va a fingir lo contrario: colisión de MMSI (dos buques reales compartiendo identificador, frecuente en flota fluvial y de remolcadores), suplantación deliberada, error de decodificación, o fallo de la estación receptora. La detección es aritmética; la causa no.',
      tech: 'Medido sobre el almacén el 2026-11-11: 1.779 saltos en 28 MMSI de 1.253 trazas. Peor caso 10.420 kn, 160 km en 30 s. Diez de los 28 son de bandera rusa, el resto en su mayoría banderas de conveniencia, y uno está en la lista de sanciones de OFAC. Los saltos de menos de 2 km o menos de 5 s se ignoran como ruido de GPS.' }
  }
};

/* AIS "ship and cargo type" codes that actually appear, in plain words. */
var SHIP_TYPES = {
  en: { 30: 'Fishing vessel', 31: 'Towing', 32: 'Towing, long tow',
    33: 'Dredging or underwater operations', 34: 'Diving operations',
    35: 'Military operations', 36: 'Sailing', 37: 'Pleasure craft',
    50: 'Pilot vessel', 51: 'Search and rescue', 52: 'Tug', 53: 'Port tender',
    55: 'Law enforcement', 58: 'Medical transport',
    60: 'Passenger ship', 70: 'Cargo ship', 80: 'Tanker', 90: 'Other' },
  es: { 30: 'Pesquero', 31: 'Remolque', 32: 'Remolque largo',
    33: 'Draga u operaciones submarinas', 34: 'Operaciones de buceo',
    35: 'Operaciones militares', 36: 'Vela', 37: 'Embarcación de recreo',
    50: 'Práctico', 51: 'Búsqueda y rescate', 52: 'Remolcador', 53: 'Barcaza de puerto',
    55: 'Autoridad', 58: 'Transporte sanitario',
    60: 'Buque de pasaje', 70: 'Buque de carga', 80: 'Petrolero o quimiquero', 90: 'Otro' }
};

/* Names that need unpacking for a general audience. Matched case-insensitively
 * against the AIS static name. */
var NAME_NOTES = {
  'NATO WARSHIP': {
    en: 'A warship of a NATO member operating under an allied task group. "NATO WARSHIP" is not a real ship name: it is a generic identity that allied navies broadcast over AIS instead of their own name, so that they are visible to merchant traffic for collision avoidance while not revealing which unit they are. In the Gulf of Finland these are usually units of Baltic Sentry, the NATO activity set up to protect subsea cables after the 2023-2025 incidents. The MMSI prefix still reveals the flag: 230 is Finland, 265 Sweden, 276 Estonia, 277 Lithuania, 278 Slovenia, 211 Germany.',
    es: 'Un buque de guerra de un país de la OTAN operando bajo una agrupación aliada. "NATO WARSHIP" no es un nombre real: es una identidad genérica que las marinas aliadas emiten por AIS en lugar de su propio nombre, para ser visibles al tráfico mercante y evitar abordajes sin revelar qué unidad son. En el golfo de Finlandia suelen ser unidades de Baltic Sentry, la actividad de la OTAN creada para proteger los cables submarinos tras los incidentes de 2023-2025. El prefijo del MMSI sí revela el pabellón: 230 es Finlandia, 265 Suecia, 276 Estonia, 277 Lituania, 278 Eslovenia, 211 Alemania.'
  },
  'FURUNOP': {
    en: 'A test transponder, not a vessel. Equipment manufacturers leave AIS units broadcasting from a bench or a dock while testing them. It moved four metres in an hour.',
    es: 'Un transpondedor de prueba, no un buque. Los fabricantes de equipos dejan unidades AIS emitiendo desde un banco o un muelle mientras las prueban. Se movió cuatro metros en una hora.'
  },
  'NAVI TEST': {
    en: 'A test transponder, not a vessel. Same as FURUNOP: it moved three metres in an hour.',
    es: 'Un transpondedor de prueba, no un buque. Igual que FURUNOP: se movió tres metros en una hora.'
  }
};

var GLOSSARY = {
  en: [
    ['AIS', 'Automatic Identification System. Every ship above a certain size broadcasts its identity, position, speed and course over VHF radio. It is self-reported, which means it can be switched off, or made to say something untrue.'],
    ['MMSI', 'The nine-digit radio identity of a vessel. The first three digits are the flag state.'],
    ['SOG', 'Speed over ground, in knots. One knot is 1.852 km/h.'],
    ['COG', 'Course over ground: the direction the ship is actually travelling.'],
    ['Heading', 'The direction the bow points. It differs from COG when wind, current or a dragged anchor push the ship sideways.'],
    ['Corridor', 'The published route of a subsea cable, power link or pipeline. Here they come from OpenStreetMap, which is open but not authoritative.'],
    ['Alert vs exposure', 'An alert is behaviour worth a human look. An exposure is only geometry: the vessel was near infrastructure. Most exposures are completely normal.'],
    ['Dark period', 'A stretch of time with no AIS position. It can mean the transmitter was off, or simply that nobody was listening.'],
    ['Drag band', 'The 1 to 5 knot range at which a ship moves while its anchor is on the seabed.']
  ],
  es: [
    ['AIS', 'Sistema de identificación automática. Todo buque por encima de cierto tamaño emite por radio VHF su identidad, posición, velocidad y rumbo. Es autodeclarado: se puede apagar, o hacer que diga algo falso.'],
    ['MMSI', 'La identidad de radio de nueve dígitos de un buque. Los tres primeros dígitos son el estado de pabellón.'],
    ['SOG', 'Velocidad sobre el fondo, en nudos. Un nudo son 1,852 km/h.'],
    ['COG', 'Rumbo sobre el fondo: la dirección en la que el buque realmente avanza.'],
    ['Rumbo de proa', 'La dirección a la que apunta la proa. Difiere del COG cuando el viento, la corriente o un ancla arrastrada empujan al buque de lado.'],
    ['Corredor', 'El trazado publicado de un cable submarino, enlace eléctrico o gasoducto. Aquí vienen de OpenStreetMap, que es abierto pero no oficial.'],
    ['Alerta y exposición', 'Una alerta es un comportamiento que merece una mirada humana. Una exposición es solo geometría: el buque estaba cerca de infraestructura. La mayoría son completamente normales.'],
    ['Periodo oscuro', 'Un intervalo sin posición AIS. Puede significar que el transmisor estaba apagado, o simplemente que nadie escuchaba.'],
    ['Banda de arrastre', 'El rango de 1 a 5 nudos al que se mueve un barco con el ancla en el fondo.']
  ]
};

var HONEST = {
  en: [
    'It cannot establish intent. Two allied warships protecting a cable produce the same kinematic signature as a vessel attacking it. No threshold fixes that.',
    'It cannot see a vessel that is not transmitting, unless satellite radar happens to cover that minute. Over the December 2024 Gulf of Finland incident, Sentinel-1 had a 61 hour 9 minute gap.',
    'It cannot separate drift from propulsion. The Copernicus Marine model for the Baltic has an 87 degree RMS error on surface current direction, validated against seven moorings for the whole sea.',
    'Its thresholds are not calibrated. They are first guesses measured against a few days of traffic, documented in the Status tab.'
  ],
  es: [
    'No puede establecer intención. Dos buques de guerra aliados protegiendo un cable producen la misma firma cinemática que uno atacándolo. Ningún umbral arregla eso.',
    'No puede ver un buque que no emite, salvo que el radar de satélite cubra justo ese minuto. Sobre el incidente de diciembre de 2024 en el golfo de Finlandia, Sentinel-1 tuvo un hueco de 61 h 9 min.',
    'No puede separar deriva de propulsión. El modelo Copernicus Marine del Báltico tiene 87 grados de error RMS en la dirección de la corriente superficial, validado contra siete fondeos para todo el mar.',
    'Sus umbrales no están calibrados. Son primeras aproximaciones medidas contra unos pocos días de tráfico, documentadas en la pestaña Estado.'
  ]
};

function explainFor(ind) {
  var e = EXPLAIN[ind]; if (!e) { return null; }
  return e[LANG] || e.en;
}
function shipTypeText(code) {
  var m = SHIP_TYPES[LANG] || SHIP_TYPES.en;
  return m[code] || (SHIP_TYPES.en[code] || null);
}
function nameNote(name) {
  if (!name) { return null; }
  var k = String(name).trim().toUpperCase();
  var hit = NAME_NOTES[k];
  if (!hit) { Object.keys(NAME_NOTES).forEach(function (key) {
    if (!hit && k.indexOf(key) >= 0) { hit = NAME_NOTES[key]; } }); }
  return hit ? (hit[LANG] || hit.en) : null;
}
