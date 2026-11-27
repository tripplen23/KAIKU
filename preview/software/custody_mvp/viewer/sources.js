/* sources.js - where every pixel and every number came from.
 *
 * A CASSINI jury will ask which of this is EU Space Programme data and which
 * is not. The honest answer has three tiers, and hiding the third one would be
 * the fastest way to lose credibility:
 *   - EU SPACE: Copernicus Sentinel products. ESA-built, EC-owned.
 *   - SPACE-ENABLED: derived from satellites but not EU, or EU data served by
 *     a third party.
 *   - NOT SPACE: terrestrial. Our AIS is coastal VHF, not satellite AIS. */
'use strict';

var SOURCES = [
  { id: 'sentinel1', tier: 'eu',
    name: 'Copernicus Sentinel-1 (GRD, IW)',
    operator: 'ESA / European Commission',
    gives: { en: 'C-band radar imagery and pass footprints over the Gulf. Sees through cloud and darkness, which optical cannot in a Finnish winter.',
             es: 'Imagen radar en banda C y huellas de pasada sobre el golfo. Atraviesa nube y oscuridad, que es lo que el óptico no puede en un invierno finlandés.' },
    via: 'Copernicus Data Space Ecosystem (catalogue + GRD) · Microsoft Planetary Computer (georeferenced tiles)',
    licence: 'Copernicus · free, full and open' },
  { id: 'sentinel2', tier: 'eu',
    name: 'Copernicus Sentinel-2 (L2A)',
    operator: 'ESA / European Commission',
    gives: { en: 'Optical context when there is daylight. Over 60°N that is roughly March to October.',
             es: 'Contexto óptico cuando hay luz. Por encima de 60°N eso es de marzo a octubre, aproximadamente.' },
    via: 'Copernicus Data Space Ecosystem (catalogue) · Microsoft Planetary Computer '
         + '(georeferenced tiles, true colour)',
    licence: 'Copernicus · free, full and open' },
  { id: 'gfw', tier: 'nonEu',
    name: 'Global Fishing Watch — behaviour events',
    operator: 'Global Fishing Watch (US non-profit)',
    gives: { en: 'Classified behaviour, not raw positions: AIS gaps judged intentional, vessel-to-vessel encounters, loitering and port visits. A second opinion on the same vessels, from another team with another model.',
             es: 'Comportamiento ya clasificado, no posiciones crudas: huecos de AIS juzgados intencionados, encuentros buque a buque, merodeo y escalas en puerto. Una segunda opinión sobre los mismos buques, de otro equipo y otro modelo.' },
    via: 'gateway.api.globalfishingwatch.org/v3 — events (behaviour) and 4wings/report '
         + '(activity grid)',
    licence: 'CC BY-SA 4.0 · attribution required',
    note: { en: 'Derived from satellite and terrestrial AIS, plus Sentinel-1 for their SAR presence product. Non-EU operator, so it is kept out of the EU tier even though it is space-derived.',
            es: 'Derivado de AIS satelital y terrestre, y de Sentinel-1 para su producto de presencia SAR. Operador no comunitario, así que se mantiene fuera del nivel UE aunque venga de satélite.' } },
  { id: 'emodnet-bathy', tier: 'enabled',
    name: 'EMODnet Bathymetry DTM',
    operator: 'European Commission (DG MARE)',
    gives: { en: 'Water depth. Drives the coastline, the isobaths and the single question that matters physically: could an anchor reach the bed here.',
             es: 'Profundidad del agua. De ahí salen la costa, las isobatas y la única pregunta que importa físicamente: ¿llegaría un ancla al fondo aquí?' },
    via: 'ows.emodnet-bathymetry.eu', licence: 'EMODnet terms · open',
    note: { en: 'Built from ship and airborne surveys, not from orbit.',
            es: 'Construido con campañas de buque y aéreas, no desde órbita.' } },
  { id: 'ais', tier: 'ground',
    name: 'AIS vessel positions',
    operator: 'Fintraffic / digitraffic.fi',
    gives: { en: 'Identity, position, speed, course and heading of every vessel in the Gulf. The spine of the whole map.',
             es: 'Identidad, posición, velocidad, rumbo y proa de cada buque del golfo. La columna vertebral de todo el mapa.' },
    via: 'meri.digitraffic.fi (REST + MQTT)', licence: 'CC BY 4.0',
    note: { en: 'Received by COASTAL VHF stations, not from orbit. This is not satellite AIS. Say so plainly: calling it space data would be false.',
            es: 'Recibido por estaciones VHF COSTERAS, no desde órbita. Esto no es AIS satelital. Decirlo claro: llamarlo dato espacial sería falso.' } },
  { id: 'osm', tier: 'ground',
    name: 'OpenStreetMap (Overpass)',
    operator: 'OpenStreetMap contributors',
    gives: { en: 'Routes of subsea cables, power links and pipelines, plus ports and anchorages.',
             es: 'Trazados de cables submarinos, enlaces eléctricos y gasoductos, más puertos y fondeaderos.' },
    via: 'overpass-api.de', licence: 'ODbL',
    note: { en: 'Crowd-sourced and not authoritative. EMODnet has an official cable layer but it holds no Finnish coverage, which is why OSM is used here.',
            es: 'Colaborativo y no oficial. EMODnet tiene una capa oficial de cables pero sin cobertura finlandesa, por eso se usa OSM.' } },
  { id: 'vayla', tier: 'ground',
    name: 'Väylävirasto navigation restrictions',
    operator: 'Finnish Transport Infrastructure Agency',
    gives: { en: 'Restricted areas and anchoring bans.',
             es: 'Áreas restringidas y prohibiciones de fondeo.' },
    via: 'WFS', licence: 'CC BY 4.0' }
];

var TIERS = {
  eu:      { en: 'EU Space Programme', es: 'Programa Espacial de la UE', cls: 'tier-eu' },
  enabled: { en: 'European open data', es: 'Dato abierto europeo', cls: 'tier-en' },
  nonEu:   { en: 'Space-derived — non-EU operator',
             es: 'Derivado de satélite — operador no comunitario', cls: 'tier-ne' },
  ground:  { en: 'Terrestrial — not space data', es: 'Terrestre — no es dato espacial', cls: 'tier-gr' }
};

function pick(o) { return o ? (o[LANG] || o.en) : ''; }

function renderSources() {
  var box = document.getElementById('sources'); if (!box) { return; }
  var m = (window.manifest || {});
  var ok = function (id) {
    var L = m.layers || {};
    if (id === 'sentinel1') { return L.sentinel1 && L.sentinel1.status === 'ok'; }
    /* Sentinel-2 no pasa por el build: lo pide el visor a la carta. Esta en
     * uso si su capa esta encendida, no si hay un fichero escrito. */
    if (id === 'sentinel2') {
      return !!(window.IMAGERY && IMAGERY.s2 && IMAGERY.s2.on);
    }
    if (id === 'gfw') {
      return (L.gfw_events && L.gfw_events.status === 'ok') ||
             (L.gfw_grid && L.gfw_grid.status === 'ok');
    }
    if (id === 'emodnet-bathy') { return L.bathymetry && L.bathymetry.status === 'ok'; }
    if (id === 'ais') { return L.tracks && L.tracks.status === 'ok'; }
    if (id === 'osm') { return L.corridors && L.corridors.status === 'ok'; }
    if (id === 'vayla') { return L.restrictions && L.restrictions.status === 'ok'; }
    return null;
  };
  var h = '<div class="block note-box"><p>' + pick({
    en: 'Three tiers, kept apart on purpose. What is EU space data, what is European open data, and what is simply terrestrial. The third tier is the one most easily misrepresented.',
    es: 'Tres niveles, separados a propósito. Qué es dato espacial de la UE, qué es dato abierto europeo y qué es simplemente terrestre. El tercero es el que más fácilmente se tergiversa.' }) +
    '</p></div>';

  ['eu', 'enabled', 'nonEu', 'ground'].forEach(function (tier) {
    var rows = SOURCES.filter(function (s) { return s.tier === tier; });
    if (!rows.length) { return; }
    h += '<h3><span class="tier ' + TIERS[tier].cls + '">' + pick(TIERS[tier]) + '</span></h3>';
    rows.forEach(function (s) {
      var st = s.status === 'planned' ? 'planned' : ok(s.id);
      var badge = st === 'planned'
        ? '<span class="badge expo">' + pick({ en: 'not used yet', es: 'aún sin usar' }) + '</span>'
        : (st === true ? '<span class="badge" style="background:#11331f;color:#6ff0a0">' +
             pick({ en: 'in use', es: 'en uso' }) + '</span>'
          : (st === false ? '<span class="badge" style="background:#3a1b1b;color:#ff9a8a">' +
             pick({ en: 'empty in this build', es: 'vacío en este build' }) + '</span>' : ''));
      h += '<details class="src ' + TIERS[tier].cls + '"><summary>' + badge +
        esc(s.name) + '</summary><div class="inner">' +
        '<div class="row"><span class="k">' + pick({ en: 'Operator', es: 'Operador' }) +
          '</span><span>' + esc(s.operator) + '</span></div>' +
        '<div class="row"><span class="k">' + pick({ en: 'Accessed via', es: 'Acceso vía' }) +
          '</span><span>' + esc(s.via) + '</span></div>' +
        '<div class="row"><span class="k">' + pick({ en: 'Licence', es: 'Licencia' }) +
          '</span><span>' + esc(s.licence) + '</span></div>' +
        '<p>' + esc(pick(s.gives)) + '</p>' +
        (s.note ? '<p class="note"><b>' + pick({ en: 'Caveat', es: 'Matiz' }) + ':</b> ' +
          esc(pick(s.note)) + '</p>' : '') +
        '</div></details>';
    });
  });
  box.innerHTML = h;
}

/* Tira permanente sobre el mapa: de un vistazo, que es espacial y que no. */
function renderSourceStrip() {
  var el = document.getElementById('srcstrip'); if (!el) { return; }
  var m = (window.manifest || {}), L_ = m.layers || {};
  var s1 = L_.sentinel1 && L_.sentinel1.status === 'ok';
  var s2 = !!(window.IMAGERY && IMAGERY.s2 && IMAGERY.s2.on);
  var gf = (L_.gfw_events && L_.gfw_events.status === 'ok') ||
           (L_.gfw_grid && L_.gfw_grid.status === 'ok');
  el.innerHTML =
    '<span class="tier tier-eu">' + pick(TIERS.eu) + '</span>' +
    '<span class="chip' + (s1 ? '' : ' off') + '">Copernicus Sentinel-1</span>' +
    '<span class="chip' + (s2 ? '' : ' off') + '">Copernicus Sentinel-2</span>' +
    (gf ? '<span class="tier tier-ne">' + pick(TIERS.nonEu) + '</span>' +
          '<span class="chip">Global Fishing Watch</span>' : '') +
    '<span class="tier tier-gr">' + pick(TIERS.ground) + '</span>' +
    '<span class="chip">AIS · Fintraffic (VHF)</span>' +
    '<span class="chip">OSM · EMODnet · Väylä</span>';
}
