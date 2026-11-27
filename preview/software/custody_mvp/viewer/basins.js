/* basins.js - las subcuencas del Baltico, de HELCOM.
 *
 * La primera version eran seis rectangulos dibujados a mano. Encuadraban
 * bien y clasificaban mal: no teselaban el mar, el 9,4 % del agua del AOI no
 * caia en ninguno y 2.218 celdas caian en dos. Un filtro que esconde dato
 * por un limite inventado es una fuente de error, no una herramienta.
 *
 * Ahora se usa la division estandar: `HELCOM subbasins level 2`, 17 unidades,
 * la que HELCOM emplea en sus evaluaciones HOLAS. Se bajan en el build
 * (custody/basins.py) y se simplifican de 2,9 M de vertices a 26 k.
 *
 * HELCOM agrupa esas 17 en 7 cuencas mayores para los techos de nutrientes
 * del Plan de Accion. La interfaz ofrece esas 7, porque diecisiete botones
 * no son una eleccion sino un formulario; el dato por debajo son las 17.
 *
 * Y una octava entrada que NO es de HELCOM y se dice: «aguas interiores».
 * El AIS trae buques del lago Ladoga, del canal de Saimaa y del Malaren, que
 * no son el mar Baltico y no estan en ninguna subcuenca. Antes desaparecian
 * del mapa al filtrar. Ahora tienen su sitio.
 */
'use strict';

var BASIN_FC = null;        /* las 17, tal cual salen del build */
var BASINS = [];            /* las 7 mayores + aguas interiores, para la UI */
var BASIN = { id: null, mask: null, outline: null };

/* Margen costero. Simplificar la costa a ~250 m mete los puertos y los
 * archipielagos unos metros «fuera» de su propia cuenca: sin margen, el
 * 20,6 % de los buques quedaba sin clasificar, y son justo los que estan
 * atracados. Con 5 km baja al 4 %, y lo que resta es de verdad agua
 * interior. El numero es el error que introduce la simplificacion, no una
 * licencia para estirar limites. */
var BASIN_EDGE_KM = 5;

var INLAND = {
  id: 'inland',
  name: { en: 'Inland waters and lakes', es: 'Aguas interiores y lagos' },
  note: { en: 'Not a HELCOM sub-basin and not the Baltic: Lake Ladoga, the Saimaa canal and Lake Malaren. AIS reaches us from there, so rather than let those vessels vanish when you focus, they get their own bucket.',
          es: 'No es una subcuenca HELCOM ni es el Baltico: lago Ladoga, canal de Saimaa y lago Malaren. Nos llega AIS de ahi, asi que en vez de dejar que esos buques desaparezcan al enfocar, tienen su propio grupo.' },
  inland: true
};

var MAJOR_NOTE = {
  KAT: { en: 'Kattegat: the Baltic approach from the North Sea.',
         es: 'Kattegat: la aproximacion al Baltico desde el mar del Norte.' },
  DS:  { en: 'Great Belt, the Sound, Kiel Bay and the Bay of Mecklenburg. The only way in or out. Every vessel entering the Baltic passes here, and we have no AIS coverage of our own.',
         es: 'Gran Belt, el Sund, la bahia de Kiel y la de Mecklemburgo. La unica entrada y salida. Todo buque que entra al Baltico pasa por aqui, y no tenemos cobertura AIS propia.' },
  BAP: { en: 'Arkona, Bornholm, Gdansk, Eastern and Western Gotland and the Northern Baltic Proper. The open centre. The November 2024 cable cuts were here — and so is the edge of our AIS coverage.',
         es: 'Arkona, Bornholm, Gdansk, Gotland oriental y occidental y el Baltico propio norte. El centro abierto. Los cortes de cable de noviembre de 2024 fueron aqui, y aqui acaba tambien nuestra cobertura AIS.' },
  GUR: { en: 'Riga, Parnu and the Irbe Strait. Nearly enclosed, with a single deep entrance.',
         es: 'Riga, Parnu y el estrecho de Irbe. Casi cerrado, con una sola entrada profunda.' },
  GUF: { en: 'Helsinki-Tallinn and the St Petersburg approaches. Balticconnector, Estlink 1 and 2, C-Lion 1. Where the 2023 and 2024 incidents happened.',
         es: 'Helsinki-Tallin y los accesos a San Petersburgo. Balticconnector, Estlink 1 y 2, C-Lion 1. Donde ocurrieron los incidentes de 2023 y 2024.' },
  BOS: { en: 'Bothnian Sea and the Aland Sea: the narrows between Sweden and Finland, dense ferry traffic through a demilitarised archipelago.',
         es: 'Mar de Botnia y mar de Aland: el estrecho entre Suecia y Finlandia, trafico denso de ferris por un archipielago desmilitarizado.' },
  BOB: { en: 'Bothnian Bay and the Quark. Carries Fenno-Skan 1 and 2, the Finland-Sweden power links. Ice-covered in winter.',
         es: 'Golfo de Botnia y el Quark. Lleva Fenno-Skan 1 y 2, las interconexiones electricas Finlandia-Suecia. Helado en invierno.' }
};

function loadBasins(fc) {
  BASIN_FC = fc;
  var by = {};
  (fc.features || []).forEach(function (f) {
    var p = f.properties, k = p.major;
    if (!by[k]) {
      by[k] = { id: k, helcom: [], parts: [], area_km2: 0,
                name: { en: p.major_name, es: p.major_name },
                note: MAJOR_NOTE[k] || { en: '', es: '' },
                bbox: p.bbox.slice() };
    }
    var g = by[k];
    g.helcom.push(p.helcom_id + ' ' + p.name);
    g.parts.push(f);
    g.area_km2 += p.area_km2 || 0;
    g.bbox[0] = Math.min(g.bbox[0], p.bbox[0]); g.bbox[1] = Math.min(g.bbox[1], p.bbox[1]);
    g.bbox[2] = Math.max(g.bbox[2], p.bbox[2]); g.bbox[3] = Math.max(g.bbox[3], p.bbox[3]);
  });
  BASINS = ['KAT', 'DS', 'BAP', 'GUR', 'GUF', 'BOS', 'BOB']
    .filter(function (k) { return by[k]; }).map(function (k) { return by[k]; });
  BASINS.push(INLAND);
  if (window.renderBasinBar) { renderBasinBar(); }
  return BASINS;
}

function basinById(id) {
  for (var i = 0; i < BASINS.length; i += 1) {
    if (BASINS[i].id === id) { return BASINS[i]; }
  }
  return null;
}
function basinName(b) { return (b.name[LANG] || b.name.en); }

/* ------------------------------------------------- punto en subcuenca */
function ptInRing(x, y, r) {
  var ins = false;
  for (var i = 0, n = r.length - 1; i < n; i += 1) {
    var x1 = r[i][0], y1 = r[i][1], x2 = r[i + 1][0], y2 = r[i + 1][1];
    if ((y1 > y) !== (y2 > y) && x < (x2 - x1) * (y - y1) / (y2 - y1) + x1) {
      ins = !ins;
    }
  }
  return ins;
}

function inFeature(lon, lat, f) {
  var bb = f.properties.bbox;
  if (lon < bb[0] - 0.05 || lon > bb[2] + 0.05 ||
      lat < bb[1] - 0.05 || lat > bb[3] + 0.05) { return false; }
  var rings = f.geometry.coordinates;
  if (!ptInRing(lon, lat, rings[0])) { return false; }
  for (var i = 1; i < rings.length; i += 1) {
    if (ptInRing(lon, lat, rings[i])) { return false; }   /* agujero */
  }
  return true;
}

function nearKm(lon, lat, f) {
  var best = 1e9, rings = f.geometry.coordinates;
  for (var i = 0; i < rings.length; i += 1) {
    var r = rings[i];
    for (var k = 0; k < r.length; k += 1) {
      var dx = (r[k][0] - lon) * 55.0, dy = (r[k][1] - lat) * 111.2;
      var d = dx * dx + dy * dy;
      if (d < best) { best = d; }
    }
  }
  return Math.sqrt(best);
}

/* Memoizado por coordenada redondeada. La via lenta (vertice mas proximo)
 * recorre 26 k vertices, y sin cache se pagaria por cada buque en cada
 * repintado. */
var _bcache = {};

function basinOf(lon, lat) {
  var key = lon.toFixed(3) + ',' + lat.toFixed(3);
  if (key in _bcache) { return _bcache[key]; }
  var out = null, i;
  for (i = 0; i < (BASIN_FC ? BASIN_FC.features.length : 0); i += 1) {
    if (inFeature(lon, lat, BASIN_FC.features[i])) {
      out = BASIN_FC.features[i].properties.major; break;
    }
  }
  if (out === null && BASIN_FC) {
    var bestD = 1e9, bestK = null;
    for (i = 0; i < BASIN_FC.features.length; i += 1) {
      var d = nearKm(lon, lat, BASIN_FC.features[i]);
      if (d < bestD) { bestD = d; bestK = BASIN_FC.features[i].properties.major; }
    }
    out = bestD <= BASIN_EDGE_KM ? bestK : 'inland';
  }
  _bcache[key] = out;
  return out;
}

function inBasin(b, lon, lat) {
  if (!b) { return true; }
  return basinOf(lon, lat) === b.id;
}

/* ----------------------------------------------------------- enfocar */
function focusBasin(id) {
  clearBasin();
  var b = basinById(id);
  if (!b) { renderBasinBar(); return; }
  BASIN.id = id;
  var bb = b.bbox;
  if (b.inland) {
    /* Las aguas interiores no son un poligono: son todo lo que no cae en
     * ninguna subcuenca. No hay contorno que dibujar, asi que no se finge
     * uno; se filtra y se encuadra en lo que haya. */
    var pts = [];
    Object.keys(HIST).forEach(function (m) {
      var p = HIST[m].pts[HIST[m].pts.length - 1];
      if (basinOf(p.lon, p.lat) === 'inland') { pts.push([p.lat, p.lon]); }
    });
    if (pts.length) { map.fitBounds(pts, { padding: [40, 40] }); }
    renderBasinBar(); basinRefresh(); return;
  }
  /* Mascara: el mundo con un agujero por cada parte de la cuenca. */
  var holes = b.parts.map(function (f) {
    return f.geometry.coordinates[0].map(function (p) { return [p[1], p[0]]; });
  });
  BASIN.mask = L.polygon(
    [[[-89, -179], [-89, 179], [89, 179], [89, -179]]].concat(holes),
    { color: null, weight: 0, fillColor: '#060b11', fillOpacity: 0.62,
      interactive: false }).addTo(map);
  BASIN.outline = L.geoJSON({ type: 'FeatureCollection', features: b.parts },
    { style: { color: '#00e5ff', weight: 1.5, dashArray: '6 5', fill: false },
      interactive: false }).addTo(map);
  map.fitBounds([[bb[1], bb[0]], [bb[3], bb[2]]], { padding: [30, 30] });
  renderBasinBar();
  basinRefresh();
}

function clearBasin() {
  if (BASIN.mask) { map.removeLayer(BASIN.mask); }
  if (BASIN.outline) { map.removeLayer(BASIN.outline); }
  BASIN = { id: null, mask: null, outline: null };
}

/* Enfocar cambia QUE datos se ven, no solo donde mira el mapa. */
function basinRefresh() {
  if (window.refreshAlertViews) { refreshAlertViews(); }
  if (window.applyVesselFilter) { applyVesselFilter(); }
  if (window.renderVesselTab) { renderVesselTab(''); }
  if (window.renderMapKey) { renderMapKey(); }
}

function renderBasinBar() {
  var el = document.getElementById('basinbar'); if (!el) { return; }
  var cur = BASIN.id ? basinById(BASIN.id) : null;
  var h = '<div class="bb-row"><span class="k">' + esc(t('basin_h')) + '</span>' +
    '<button class="btn bb' + (cur ? '' : ' primary') + '" data-basin="">' +
      esc(t('basin_all')) + '</button>' +
    BASINS.map(function (b) {
      return '<button class="btn bb' + (cur && cur.id === b.id ? ' primary' : '') +
        (b.inland ? ' bb-inland' : '') +
        '" data-basin="' + b.id + '">' + esc(basinName(b)) + '</button>'; }).join('') +
    '</div>';
  if (cur) {
    h += '<div class="bb-info"><p class="note">' +
      esc(cur.note[LANG] || cur.note.en) + '</p>' +
      (cur.helcom ? '<p class="note">' + esc(t('basin_helcom')) + ': ' +
        esc(cur.helcom.join(' · ')) + '</p>' : '') + '</div>';
  }
  el.innerHTML = h;
  el.querySelectorAll('[data-basin]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var id = btn.dataset.basin;
      if (!id) { clearBasin(); map.fitBounds(AOI, { padding: [20, 20] });
                 renderBasinBar(); basinRefresh(); }
      else { focusBasin(id); }
    });
  });
}
