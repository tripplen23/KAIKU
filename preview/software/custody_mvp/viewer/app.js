/* Custody MVP - visor. Leaflet 1.9.4 servido localmente (vendor/leaflet).
 * Sin CDN, sin build step, sin framework. Las unicas capas que salen a la red
 * son las dos que estan explicitamente marcadas y apagadas por defecto.
 * Todos los GeoJSON los genera ../build.py en viewer/data/. */
'use strict';

var BRAND = { brand: 'Custody', team: '', tagline: '', defaultLang: 'en',
              showGamification: true };

/* Valor de arranque: el mapa tiene que pintarse antes de que llegue el
 * manifest. En cuanto llega, `setAoi` lo sustituye por el AOI REAL del build.
 * Tenerlo a fuego hacia que el modo en vivo filtrara al golfo aunque el build
 * fuera del Baltico entero: 543 buques en pantalla de los 1.070 que llegaban.
 * Mismo fallo que el bbox codificado de corridors.py, en el otro extremo. */
var AOI = [[53.5, 9.0], [66.0, 30.5]];

function setAoi(a) {
  if (!a || a.length !== 4) { return; }
  AOI = [[a[1], a[0]], [a[3], a[2]]];     /* manifest: lon,lat,lon,lat */
}
var COLOR = { power: '#ff6b6b', telecom: '#4fc3f7', pipeline: '#a78bfa',
              cable_unspecified: '#7f8c9b', unspecified: '#7f8c9b' };
/* Los niveles que publica HELCOM (capa 14) son -10, -20, -50, -100, -200...
 * Antes se derivaban a 20/50/80/100 de nuestra propia rejilla; el 80 no
 * existe en el dato de HELCOM y a cambio aparece el 10, que es el que marca
 * donde un casco de calado medio empieza a tener problemas. */
var ISO_COLOR = { 10: '#17304a', 20: '#1d3b52', 50: '#24506e', 100: '#3a7faa' };

/* minZoom/maxZoom FIJADOS en el mapa, a proposito y de forma estructural.
 *
 * Leaflet calcula el zoom minimo asi:
 *   getMinZoom: options.minZoom === undefined ? this._layersMinZoom || 0 : ...
 * o sea, si el mapa no lo fija, CUALQUIER capa con `minZoom` se lo impone al
 * mapa entero. Paso exactamente eso: el mosaico SAR declaro minZoom 8 porque
 * el tiler no sirve por debajo, y el resultado fue que se desactivo el boton
 * de alejar en toda la aplicacion.
 *
 * Una limitacion de DISPONIBILIDAD DE DATOS nunca puede convertirse en una
 * limitacion de NAVEGACION. Si no hay imagen, no se pinta imagen; el usuario
 * sigue pudiendo moverse por donde quiera. Fijarlo aqui cierra la puerta a que
 * vuelva a pasar con cualquier capa futura. */
var map = L.map('map', { preferCanvas: true, zoomControl: true,
                         attributionControl: true, minZoom: 3, maxZoom: 18 });
map.fitBounds(AOI, { padding: [8, 8] });
map.attributionControl.setPrefix(BRAND.brand || 'Custody');
L.control.scale({ metric: true, imperial: false, maxWidth: 180,
                  position: 'bottomright' }).addTo(map);

var layers = {};        // nombre -> L.Layer
var manifest = null;
var alertFeatures = [];

function j(url) { return fetch(url).then(function (r) {
  if (!r.ok) { throw new Error(url + ' -> HTTP ' + r.status); } return r.json(); }); }

function esc(s) { return String(s === null || s === undefined ? '' : s)
  .replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }

function iso(ms) { return ms ? new Date(ms).toISOString().replace('T', ' ').slice(0, 19) + 'Z' : '-'; }

function table(obj, skip) {
  var h = '';
  Object.keys(obj).forEach(function (k) {
    if (skip && skip.indexOf(k) >= 0) { return; }
    var v = obj[k];
    if (v === null || v === undefined || v === '') { return; }
    if (typeof v === 'object') { v = JSON.stringify(v); }
    h += '<div class="row"><span class="k">' + esc(k) + '</span><span>' + esc(v) + '</span></div>';
  });
  return h;
}

/* ------------------------------------------------------------ capas base */

/* La costa se guarda en una rejilla gruesa ademas de pintarse: el detector
 * SAR la consulta para tirar los blancos que caen en tierra o pegados a
 * ella. Sin esto, roca e isla se detectan igual de bien que un casco. */
var COASTBINS = null;
var COASTBIN_DEG = 0.02;

function indexCoast(fc) {
  COASTBINS = {};
  (fc.features || []).forEach(function (f) {
    var parts = f.geometry.type === 'MultiLineString'
      ? f.geometry.coordinates : [f.geometry.coordinates];
    parts.forEach(function (line) {
      line.forEach(function (c) {
        var key = Math.round(c[0] / COASTBIN_DEG) + '|' + Math.round(c[1] / COASTBIN_DEG);
        (COASTBINS[key] = COASTBINS[key] || []).push(c);
      });
    });
  });
}

/* Metros al vertice de costa mas proximo, o Infinity si no hay ninguno cerca.
 * Se miran las nueve celdas vecinas, asi que el alcance util es ~2 km. */
function distToCoastM(lon, lat) {
  if (!COASTBINS) { return Infinity; }
  var bx = Math.round(lon / COASTBIN_DEG), by = Math.round(lat / COASTBIN_DEG);
  var best = Infinity;
  for (var i = -1; i <= 1; i += 1) {
    for (var j = -1; j <= 1; j += 1) {
      var arr = COASTBINS[(bx + i) + '|' + (by + j)];
      if (!arr) { continue; }
      for (var k = 0; k < arr.length; k += 1) {
        var d = haversineM(lon, lat, arr[k][0], arr[k][1]);
        if (d < best) { best = d; }
      }
    }
  }
  return best;
}

/* addCoastline() se borro con la capa horneada. La costa la dibuja ahora
 * coasthd.js por recuadros, desde HELCOM, cacheada por el proxy. */
/* Las estaciones de AISHub. No es decorado: dibuja cuanta cobertura ajena
 * existe donde la nuestra no llega. Las del hueco van en ambar y mas grandes,
 * porque son el argumento. */
function addAisHub(fc) {
  layers.aishub = L.geoJSON(fc, {
    pointToLayer: function (f, ll) {
      var g = f.properties.in_gap;
      return L.circleMarker(ll, {
        radius: g ? 5 : 3, color: g ? '#e0a33a' : '#5b7083',
        weight: g ? 2 : 1, fillColor: g ? '#e0a33a' : '#4a6378',
        fillOpacity: g ? 0.8 : 0.5
      });
    },
    onEachFeature: function (f, l) {
      var p = f.properties;
      l.bindPopup('<h4>' + esc(p.location || '?') + '</h4>' +
        '<div class="note">' + esc((p.country || '').toUpperCase()) +
        ' · AISHub station ' + esc(p.id) + '</div>' +
        (p.in_gap ? '<div class="block caution"><p>' + esc(t('ah_gap')) +
          '</p></div>' : '') +
        '<p class="note">' + esc(t('ah_note')) + '</p>');
    }
  });
}

function addIsobaths(fc) {
  layers.isobaths = L.geoJSON(fc, {
    style: function (f) {
      return { color: ISO_COLOR[f.properties.depth_m] || '#2d6689',
               weight: f.properties.depth_m === 100 ? 1.4 : 0.8, fill: false,
               interactive: false };
    }
  }).addTo(map);
}

function addCorridorsOther(fcOther) {
  layers.corridors_other = L.geoJSON(fcOther, { style: { color: '#43525f', weight: 1,
    opacity: 0.55 }, onEachFeature: corridorPopup });
}

function addCorridors(fcTrunk, fcOther) {
  if (fcOther) { addCorridorsOther(fcOther); }
  layers.corridors = L.geoJSON(fcTrunk, {
    style: function (f) {
      return { color: COLOR[f.properties.asset_class] || '#7f8c9b', weight: 3, opacity: 0.95 };
    }, onEachFeature: corridorPopup
  }).addTo(map);
}

function corridorPopup(f, lyr) {
  var p = f.properties;
  lyr.bindPopup('<h4>' + esc(p.name || '(sin nombre en OSM)') + '</h4>' +
    table({ clase: p.asset_class, 'longitud_km': (p.length_m / 1000).toFixed(1),
            operador: p.operator, propietario: p.owner, vayla_id: p.vayla_id,
            osm: p.osm_id, trunk: p.trunk }) +
    '<div class="note">OpenStreetMap, ODbL 1.0</div>');
}

function addPorts(fc) {
  layers.ports = L.geoJSON(fc, {
    style: { color: '#6b5b2a', weight: 1, fillColor: '#6b5b2a', fillOpacity: 0.18 },
    pointToLayer: function (f, ll) {
      return L.circle(ll, { radius: f.properties.buffer_m || 1500, color: '#6b5b2a',
                            weight: 1, fillOpacity: 0.12 });
    },
    onEachFeature: function (f, l) {
      l.bindPopup('<h4>' + esc(f.properties.name || 'port/anchorage') + '</h4>' +
        '<div class="note">' + esc(t('mask_what')) + '</div>' +
        table({ kind: f.properties.kind, buffer_m: f.properties.buffer_m }) +
        '<div class="note">' + esc(t('mask_see')) + '</div>');
    }
  });
}

/* Filtros en caliente. La deteccion ya esta calculada; lo que se decide aqui
 * es si se MUESTRA. Apagar un filtro revela lo que el build habria descartado.
 * Por defecto todos encendidos: es el comportamiento operativo. */
var FILTERS = {};
function filterKeys() {
  var ks = {};
  (window.suppressedFeatures || []).forEach(function (f) {
    ks[f.properties.key] = true; });
  return Object.keys(ks).sort();
}
function filterOn(key) { return FILTERS[key] !== false; }

function renderFilterUI() {
  var box = document.getElementById('filters');
  if (!box) { return; }
  var keys = filterKeys();
  if (!keys.length) { box.innerHTML = '<div class="note">' + esc(t('no_filters')) + '</div>'; return; }
  var h = '<p class="note">' + esc(t('filters_note')) + '</p>';
  keys.forEach(function (k) {
    var n = (window.suppressedFeatures || []).filter(function (f) {
      return f.properties.key === k; }).length;
    h += '<label><input type="checkbox" data-filter="' + esc(k) + '"' +
      (filterOn(k) ? ' checked' : '') + '> <span>' + esc(k) +
      '</span> <span class="note">(' + n + ')</span></label>';
  });
  box.innerHTML = h;
  box.querySelectorAll('input[data-filter]').forEach(function (cb) {
    cb.addEventListener('change', function () {
      FILTERS[cb.dataset.filter] = cb.checked;
      refreshAlertViews();
    });
  });
}

/* Union de alertas reales y de las suprimidas cuyo filtro esta apagado. */
var TIME_FILTER = { on: true, windowMs: 6 * 3600e3 };

/* Controles de operador. Todo lo de aqui actua sobre campos que YA estan en
 * el GeoJSON, asi que se aplica en caliente sin rehacer el build. No se
 * reimplementa la deteccion en el navegador: los umbrales que generan las
 * alertas viven en custody/indicators.py y se muestran, no se tocan. Lo que
 * el operador decide aqui es que parte de lo detectado quiere ver.
 *   minScore   composite_score minimo
 *   maxDistM   distancia maxima al corredor (evidence.min_distance_m)
 *   minDurMin  duracion minima del episodio (evidence.duration_s)
 *   maxDepthM  profundidad maxima: por encima el ancla no llega al fondo
 *   hideSvc    oculta los que declaran ser buque de servicio o militar
 *   inds/sevs  indicador y severidad */
var OPS = { minScore: 0, maxDistM: null, minDurMin: 0, maxDepthM: null,
            hideSvc: false, inds: {}, sevs: {}, onlyUnseen: false };

function opsBounds() {
  var all = (alertFeatures || []).concat(window.suppressedFeatures || []);
  var b = { score: 0, dist: 0, dur: 0, depth: 0 };
  all.forEach(function (f) {
    var p = f.properties, e = p.evidence || {};
    b.score = Math.max(b.score, p.composite_score || 0);
    if (e.min_distance_m) { b.dist = Math.max(b.dist, e.min_distance_m); }
    if (e.duration_s) { b.dur = Math.max(b.dur, e.duration_s / 60); }
    if (e.depth_m) { b.depth = Math.max(b.depth, e.depth_m); }
  });
  b.score = Math.ceil(b.score * 100) / 100 || 1;
  b.dist = Math.ceil(b.dist / 100) * 100 || 5000;
  b.dur = Math.ceil(b.dur / 10) * 10 || 120;
  b.depth = Math.ceil(b.depth / 10) * 10 || 100;
  return b;
}

function opsPass(f) {
  var p = f.properties, e = p.evidence || {};
  /* El filtro de buques tambien manda aqui. Si el casco esta oculto, su
   * alerta tambien: dejar la alerta de un buque invisible en pantalla
   * contradice lo que dice el aviso de «se ven 11 de 530». */
  if (window.vesselPassesFilter && !vesselPassesFilter(p.mmsi)) { return false; }
  if (OPS.onlyUnseen && isSeen(p)) { return false; }
  if ((p.composite_score || 0) < OPS.minScore) { return false; }
  if (OPS.inds[p.indicator] === false) { return false; }
  if (OPS.sevs[severityOf(p)] === false) { return false; }
  if (OPS.hideSvc && p.service_craft_declared) { return false; }
  if (OPS.maxDistM !== null && e.min_distance_m !== undefined &&
      e.min_distance_m !== null && e.min_distance_m > OPS.maxDistM) { return false; }
  if (OPS.minDurMin > 0 && e.duration_s !== undefined && e.duration_s !== null &&
      e.duration_s / 60 < OPS.minDurMin) { return false; }
  if (OPS.maxDepthM !== null && e.depth_m !== undefined && e.depth_m !== null &&
      e.depth_m > OPS.maxDepthM) { return false; }
  return true;
}

function renderOpsFilters() {
  var box = document.getElementById('thr-live'); if (!box) { return; }
  var b = opsBounds();
  var inds = {}, sevs = {};
  (alertFeatures || []).concat(window.suppressedFeatures || []).forEach(function (f) {
    inds[f.properties.indicator] = (inds[f.properties.indicator] || 0) + 1;
    var k = severityOf(f.properties); sevs[k] = (sevs[k] || 0) + 1;
  });
  var sl = function (id, label, max, step, val, unit) {
    return '<div class="ops"><label for="' + id + '">' + esc(label) +
      ' <b id="' + id + '-v">' + (val === null ? esc(t('ops_any')) : val + (unit ? ' ' + unit : '')) +
      '</b></label><input type="range" id="' + id + '" min="0" max="' + max +
      '" step="' + step + '" value="' + (val === null ? max : val) + '"></div>';
  };
  var h = sl('op-score', t('ops_score'), b.score, b.score / 100, OPS.minScore, '') +
    sl('op-dist', t('ops_dist'), b.dist, 50, OPS.maxDistM, 'm') +
    sl('op-dur', t('ops_dur'), b.dur, 1, OPS.minDurMin, 'min') +
    sl('op-depth', t('ops_depth'), b.depth, 1, OPS.maxDepthM, 'm') +
    '<label><input type="checkbox" id="op-svc"' + (OPS.hideSvc ? ' checked' : '') +
      '> ' + esc(t('ops_svc')) + '</label>' +
    '<div class="ops-chips"><span class="k">' + esc(t('ops_ind')) + '</span>' +
    Object.keys(inds).sort().map(function (k) {
      return '<label class="chipbox"><input type="checkbox" data-ind="' + esc(k) + '"' +
        (OPS.inds[k] === false ? '' : ' checked') + '> ' + esc(k) +
        ' <span class="note">' + inds[k] + '</span></label>'; }).join('') + '</div>' +
    '<div class="ops-chips"><span class="k">' + esc(t('ops_sev')) + '</span>' +
    ['extreme', 'severe', 'moderate', 'minor', 'info'].filter(function (k) {
      return sevs[k]; }).map(function (k) {
      return '<label class="chipbox"><input type="checkbox" data-sev="' + k + '"' +
        (OPS.sevs[k] === false ? '' : ' checked') + '><i class="dot" style="background:' +
        SEVERITY[k].colour + '"></i>' + esc(SEVERITY[k].label[LANG] || SEVERITY[k].label.en) +
        ' <span class="note">' + sevs[k] + '</span></label>'; }).join('') + '</div>' +
    '<div class="btn-row"><button class="btn" id="op-reset">' + esc(t('ops_reset')) +
      '</button></div>';
  box.innerHTML = h;

  var bind = function (id, key, unit, isMax) {
    var el = document.getElementById(id), out = document.getElementById(id + '-v');
    el.addEventListener('input', function () {
      var v = +el.value;
      /* Un deslizador al tope no es un filtro: significa «sin limite». */
      OPS[key] = (isMax && v >= +el.max) ? null : v;
      out.textContent = OPS[key] === null ? t('ops_any')
        : (Math.round(v * 1000) / 1000) + (unit ? ' ' + unit : '');
      refreshAlertViews();
    });
  };
  bind('op-score', 'minScore', '', false);
  bind('op-dist', 'maxDistM', 'm', true);
  bind('op-dur', 'minDurMin', 'min', false);
  bind('op-depth', 'maxDepthM', 'm', true);
  document.getElementById('op-svc').addEventListener('change', function (e) {
    OPS.hideSvc = e.target.checked; refreshAlertViews(); });
  box.querySelectorAll('[data-ind]').forEach(function (cb) {
    cb.addEventListener('change', function () {
      OPS.inds[cb.dataset.ind] = cb.checked; refreshAlertViews(); }); });
  box.querySelectorAll('[data-sev]').forEach(function (cb) {
    cb.addEventListener('change', function () {
      OPS.sevs[cb.dataset.sev] = cb.checked; refreshAlertViews(); }); });
  document.getElementById('op-reset').addEventListener('click', function () {
    OPS = { minScore: 0, maxDistM: null, minDurMin: 0, maxDepthM: null,
            hideSvc: false, inds: {}, sevs: {} };
    renderOpsFilters(); refreshAlertViews();
  });
}

/* skipBasin: devuelve lo que se veria SIN el filtro de cuenca. Lo usa el
 * aviso de «hay N ocultas», que si no contaria tambien las que ya escondia
 * la ventana temporal y diria «444 ocultas» con cero en pantalla por otro
 * motivo. Un aviso que exagera deja de leerse. */
function visibleAlertFeatures(skipBasin) {
  var out = alertFeatures.slice();
  /* La cuenca enfocada FILTRA, no solo atenua. Enfocar el golfo de Finlandia
   * y seguir contando 259 alertas del Baltico entero en la lista convierte el
   * foco en un zoom decorativo. Lo que se esconde se cuenta y se dice. */
  if (!skipBasin && window.BASIN && BASIN.id) {
    var b = basinById(BASIN.id);
    if (b) {
      out = out.filter(function (f) {
        var c = f.geometry.coordinates;
        return inBasin(b, c[0], c[1]);
      });
    }
  }
  (window.suppressedFeatures || []).forEach(function (f) {
    if (!filterOn(f.properties.key)) { out.push(f); }
  });
  out = out.filter(opsPass);
  /* Las alertas tambien son un estado en el tiempo: una alerta de hace tres
   * dias no describe el instante del cursor. Se muestran las que caen en una
   * ventana alrededor del cursor; las sin marca de tiempo siempre. */
  if (TIME_FILTER.on && typeof TIME !== 'undefined' && TIME.cursor !== null &&
      TIME.cursor !== undefined) {
    var c = TIME.cursor, w = TIME_FILTER.windowMs;
    out = out.filter(function (f) {
      var t = f.properties.ts_ms;
      return !t || Math.abs(t - c) <= w;
    });
  }
  return out;
}

/* «Hay cosas que no estas viendo», con el numero y con la salida.
 *
 * El foco por cuenca esconde datos a proposito, y esconder sin decir cuanto
 * es la forma mas facil de que alguien saque una conclusion sobre un mar
 * entero mirando un golfo. Cuenta TAMBIEN lo que no cae en ninguna cuenca:
 * seis rectangulos no teselan el Baltico y ese resto existe.
 */
function basinFilterNote(kind) {
  if (!window.BASIN || !BASIN.id) { return ''; }
  var b = basinById(BASIN.id);
  if (!b) { return ''; }
  var total = 0, shown = 0, nowhere = 0;
  if (kind === 'alerts') {
    /* Solo las que los DEMAS filtros dejarian pasar. */
    visibleAlertFeatures(true).forEach(function (f) {
      var c = f.geometry.coordinates;
      total += 1;
      if (inBasin(b, c[0], c[1])) { shown += 1; }
      else if (!anyBasin(c[0], c[1])) { nowhere += 1; }
    });
  } else {
    Object.keys(HIST).forEach(function (m) {
      var pts = HIST[m].pts;
      if (!pts || !pts.length) { return; }
      if (window.vesselVisible && !vesselVisible(m)) { return; }
      var p = pts[pts.length - 1];
      total += 1;
      if (inBasin(b, p.lon, p.lat)) { shown += 1; }
      else if (!anyBasin(p.lon, p.lat)) { nowhere += 1; }
    });
  }
  var hidden = total - shown;
  if (!hidden) { return ''; }
  return '<div class="basin-note">' +
    '<b>' + hidden + '</b> ' + esc(t('bn_hidden_' + kind, { b: basinName(b) })) +
    (nowhere ? ' <span class="note">' +
      esc(t('bn_nowhere', { n: nowhere })) + '</span>' : '') +
    ' <button class="btn small js-basin-clear">' + esc(t('bn_show_all')) +
    '</button></div>';
}

function anyBasin(lon, lat) {
  for (var i = 0; i < BASINS.length; i += 1) {
    if (inBasin(BASINS[i], lon, lat)) { return true; }
  }
  return false;
}

function bindBasinClear(box) {
  box.querySelectorAll('.js-basin-clear').forEach(function (b) {
    b.addEventListener('click', function () {
      clearBasin();
      map.fitBounds(AOI, { padding: [20, 20] });
      renderBasinBar();
      if (window.basinRefresh) { basinRefresh(); }
    });
  });
}

function refreshAlertViews() {
  var vis = visibleAlertFeatures();
  renderAlertBar();
  renderAlertList(vis);
  if (!ALERTS_VISIBLE) { vis = []; }
  if (layers.alerts) { map.removeLayer(layers.alerts); }
  if (layers.exposure) { map.removeLayer(layers.exposure); }
  var mk2 = function (kind, radius) {
    return L.geoJSON({ type: 'FeatureCollection',
        features: vis.filter(function (f) { return f.properties.kind === kind; }) }, {
      pointToLayer: function (f, ll) {
        var p = f.properties;
        return L.circleMarker(ll, { radius: radius, color: sevRing(p), weight: 2,
          fillColor: sevColour(p), fillOpacity: 0.45 });
      },
      onEachFeature: function (f, l) { l.bindPopup(alertPopup(f.properties), { maxWidth: 300 }); }
    }).addTo(map);
  };
  layers.alerts = mk2('alert', 10);
  layers.exposure = mk2('exposure', 5);
  if (layers.suppressed_live) { map.removeLayer(layers.suppressed_live); }
  var shown = (window.suppressedFeatures || []).filter(function (f) {
    return !filterOn(f.properties.key); });
  layers.suppressed_live = L.geoJSON({ type: 'FeatureCollection', features: shown }, {
    pointToLayer: function (f, ll) {
      return L.circleMarker(ll, { radius: 7, color: '#c084fc', weight: 2,
        fillColor: '#7c3aed', fillOpacity: 0.45, dashArray: '3 3' });
    },
    onEachFeature: function (f, l) {
      var p = f.properties;
      l.bindPopup('<h4>' + esc(t('unfiltered_h')) + '</h4>' +
        '<div class="note">' + esc(t('unfiltered_why')) + '</div>' +
        table({ filter: p.key, mmsi: p.mmsi, t: p.ts ? iso(p.ts) : null,
                mask: p.mask, depth_m: p.depth_m, sampled: p.sampled }),
        { maxWidth: 300 });
    }
  }).addTo(map);
}

function addSuppressed(fc) {
  window.suppressedFeatures = fc.features.map(function (f) {
    var p = f.properties;
    p.kind = 'suppressed';
    p.indicator = p.key.replace(/^.*_(IND-\d+)$/, '$1');
    p.ts_ms = p.ts || null;
    p.score = 0; p.composite_score = 0;
    return f;
  });
  renderFilterUI();
  var tfo = document.getElementById('tf-on'), tfw = document.getElementById('tf-win');
  if (tfo && tfw && !tfw.dataset.bound) {
    tfw.dataset.bound = '1';
    tfw.innerHTML = [[1, '1 h'], [6, '6 h'], [24, '24 h'], [72, '3 d'], [0, t('range_all')]]
      .map(function (o) {
        return '<option value="' + o[0] + '"' +
          (o[0] * 3600e3 === TIME_FILTER.windowMs ? ' selected' : '') + '>' +
          esc(o[1]) + '</option>'; }).join('');
    tfo.addEventListener('change', function () {
      TIME_FILTER.on = tfo.checked; refreshAlertViews(); });
    tfw.addEventListener('change', function () {
      var v = +tfw.value;
      TIME_FILTER.on = v > 0; tfo.checked = v > 0;
      if (v > 0) { TIME_FILTER.windowMs = v * 3600e3; }
      refreshAlertViews();
    });
  }
  /* Lo que los filtros han descartado, con el motivo. Apagada por defecto:
   * es una capa de auditoria, no de operacion. */
  layers.suppressed = L.geoJSON(fc, {
    pointToLayer: function (f, ll) {
      return L.circleMarker(ll, { radius: 5, color: '#8e7cc3', weight: 1.5,
        fillColor: '#5b4b8a', fillOpacity: 0.5, dashArray: '2 2' });
    },
    onEachFeature: function (f, l) {
      var p = f.properties;
      l.bindPopup('<h4>' + esc(t('suppressed_h')) + '</h4>' +
        '<div class="note">' + esc(t('suppressed_why')) + '</div>' +
        '<div class="note">' + esc(t('sup_what')) + '</div>' +
        table({ reason: p.key, indicator: (p.key || '').split('_').pop(),
                mmsi: p.mmsi, t: p.ts ? iso(p.ts) : null,
                mask: p.mask, depth_m: p.depth_m }), { maxWidth: 300 });
    }
  });
}

function addRestrictions(fc) {
  /* Väylävirasto. Las de PROHIBICION DE FONDEO en rojo y encendidas; el resto
   * (limite de velocidad, estela, motor) apagadas: son ruido para este caso. */
  function mk(ban, color, on) {
    var lyr = L.geoJSON(fc, {
      filter: function (f) { return !!f.properties.anchoring_prohibited === ban; },
      style: { color: color, weight: ban ? 2 : 1, fillColor: color,
               fillOpacity: ban ? 0.25 : 0.08, dashArray: ban ? null : '3 4' },
      onEachFeature: function (f, l) {
        var p = f.properties;
        l.bindPopup('<h4>' + esc(p.restriction_en) + '</h4>' +
          table({ 'tipo (fi)': p.restriction_fi, lugar: p.place,
                  magnitud: p.magnitude, 'vigente desde': p.valid_from,
                  'vigente hasta': p.valid_to, diaarinumero: p.diaarinumero,
                  registro: p.source_register, 'estado': p.decision_state,
                  'vayla_id': p.vayla_id, excepcion: p.exception }) +
          '<div class="note">Väylävirasto, datos abiertos, CC BY 4.0</div>',
          { maxWidth: 360 });
      }
    });
    if (on) { lyr.addTo(map); }
    return lyr;
  }
  layers.anchor_ban = mk(true, '#ff3b30', true);
  layers.restrictions = mk(false, '#8a7f5a', false);
}

var tracksFc = null;
function addTracks(fc) {
  tracksFc = fc;
  buildTracksLayer();
}

/* Las capas de trazas y de ultima posicion se reconstruyen cuando cambia el
 * filtro de buques: Leaflet no sabe filtrar un GeoJSON ya montado, y es mas
 * barato rehacerlo que llevar un indice de capa a capa. */
function buildTracksLayer() {
  var on = !layers.tracks || map.hasLayer(layers.tracks);
  if (layers.tracks) { map.removeLayer(layers.tracks); }
  layers.tracks = L.geoJSON(tracksFc, {
    filter: function (f) { return visibleOnMap(f.properties.mmsi); },
    style: { color: '#3d6a8a', weight: 1, opacity: 0.55 },
    onEachFeature: function (f, l) {
      var p = f.properties;
      l.bindPopup('<h4>' + esc(p.name || ('MMSI ' + p.mmsi)) + '</h4>' +
        table({ mmsi: p.mmsi, destino: p.destination, calado_m: p.draught_m,
                fixes: p.fixes, tramos: p.segments,
                sog_min_kn: p.sog_min_kn, sog_max_kn: p.sog_max_kn,
                desde: iso(p.t_start_ms), hasta: iso(p.t_end_ms) }) +
        '<div class="note">Fintraffic / digitraffic.fi, CC 4.0 BY</div>');
    }
  });
  if (on) { layers.tracks.addTo(map); }
}

var positionsFc = null;
/* Ya no se pinta como capa. El dato sigue haciendo falta por dos cosas: la
 * ficha de buque y, sobre todo, sembrar en el historial los buques oidos una
 * sola vez (ver seedSingleFixVessels en time.js). Lo que se pintaba era la
 * ultima posicion conocida de cada buque, que es UN punto del mismo
 * historial que ya recorre la linea temporal: 884 de 1.207 marcadores caian
 * exactamente encima del ultimo fix de la traza. */
function addPositions(fc) {
  positionsFc = fc;
}

function alertPopup(p) {
  /* Resumen corto. El detalle completo va al panel lateral, que si tiene
   * scroll: la version anterior metia la tabla entera de evidencia en el popup
   * y se salia de la pantalla. */
  var ex = explainFor(p.indicator);
  var e = p.evidence || {};
  var bits = [];
  if (e.corridor) { bits.push(esc(e.corridor) + ' @ ' + Math.round(e.min_distance_m) + ' m'); }
  if (e.depth_m !== undefined && e.depth_m !== null) { bits.push(e.depth_m + ' m'); }
  if (e.duration_s) { bits.push(Math.round(e.duration_s / 60) + ' min'); }
  var g = gfwMatch(p.mmsi, p.ts_ms);
  return '<h4>' + esc(p.name || ('MMSI ' + p.mmsi)) + '</h4>' +
    '<div class="note">' + esc(p.indicator) + ' · ' +
      esc(shipTypeText(p.ship_type) || p.ship_type_text || '') + '</div>' +
    (ex ? '<p style="margin:6px 0">' + esc(ex.what) + '</p>' : '') +
    (bits.length ? '<div class="note">' + bits.join(' · ') + '</div>' : '') +
    (g ? '<div class="note corro">✓ ' + esc(t('gfw_corroborated', { e: g.event_type })) +
         '</div>' : '') +
    '<div class="btn-row"><button class="btn js-detail" data-mmsi="' +
      esc(p.mmsi) + '" data-ind="' + esc(p.indicator) + '">' +
      esc(t('what_is_this')) + '</button></div>';
}

/* ---------------------------------------------- detalle auto-explicativo */

var SEEN = {};  /* ui.js lo rellena desde localStorage */

function evidenceRows(e) { return table(e, ['fix_keys']); }

/* ---------------------------------------------- lo que la fusion aporta */
/* Esta herramienta no es un visor de AIS con capas encima: su valor es que
 * CRUZA fuentes independientes y, cuando el cruce dice algo que ninguna
 * fuente dice sola, hay que decirlo con todas las letras. Un MVP que se
 * enseña a un comprador tiene que señalar su propia aportacion; si el lector
 * tiene que deducirla, no la va a ver.
 *
 * Cada fila es: que se cruzo, que salio, y de donde sale cada mitad. Nada
 * aparece aqui si no hay dos fuentes DISTINTAS detras. */
function fusionRows(p, e) {
  var rows = [];
  var vi = vinfo(p.mmsi) || {};

  if (vi.sanctions && vi.sanctions.length) {
    var s0 = vi.sanctions[0];
    rows.push({ k: 'fus_sanction',
      v: t('fus_sanction_v', { l: s0.list }),
      src: 'AIS (Fintraffic) × ' + s0.list });
  }
  if (e.corridor) {
    rows.push({ k: 'fus_corridor',
      v: t('fus_corridor_v', { c: e.corridor, m: Math.round(e.min_distance_m) }),
      src: 'AIS (Fintraffic) × OpenStreetMap' });
  }
  if (e.depth_m !== undefined && e.depth_m !== null) {
    rows.push({ k: 'fus_depth',
      v: t(e.depth_m <= 80 ? 'fus_depth_yes' : 'fus_depth_no', { d: Math.round(e.depth_m) }),
      src: 'AIS (Fintraffic) × EMODnet Bathymetry' });
  }
  if (e.anchoring_prohibited_area) {
    rows.push({ k: 'fus_ban', v: esc(e.anchoring_prohibited_area),
      src: 'AIS (Fintraffic) × Väylävirasto' });
  }
  if (e.military_area) {
    rows.push({ k: 'fus_mil', v: t('fus_mil_v'),
      src: 'AIS (Fintraffic) × EMODnet Human Activities' });
  }
  if (e.nearest_wreck) {
    rows.push({ k: 'fus_wreck',
      v: t('fus_wreck_v', { n: e.nearest_wreck.name,
                            m: Math.round(e.nearest_wreck.distance_m) }),
      src: 'AIS (Fintraffic) × EMODnet wrecks' });
  }
  var g = gfwMatch(p.mmsi, p.ts_ms);
  if (g) {
    rows.push({ k: 'fus_gfw', v: t('fus_gfw_v', { e: g.event_type }),
      src: 'AIS (Fintraffic) × Global Fishing Watch' });
  }
  return rows;
}

function fusionBlock(p, e) {
  var rows = fusionRows(p, e);
  if (!rows.length) { return ''; }
  return '<div class="block fusion"><h4>&#9881; ' + esc(t('fus_h', { n: rows.length })) +
    '</h4>' +
    rows.map(function (r) {
      return '<div class="fus-row"><div class="fus-v">' + r.v + '</div>' +
        '<div class="fus-src">' + esc(r.src) + '</div></div>'; }).join('') +
    '<p class="note">' + esc(t('fus_note')) + '</p></div>';
}

/* Contexto del lugar: donde cae la alerta cambia lo que significa. */
function seabedBlock(e) {
  if (!e || (!e.military_area && !e.munitions_area && !e.nearest_wreck)) { return ''; }
  var h = '';

  h += '<div class="block' + (e.military_area ? ' note-box' : '') + '"><h4>' +
      esc(t('seabed_h')) + '</h4>' +
      (e.military_area ? '<div class="row"><span class="k">' + esc(t('sb_military')) +
        '</span><span>' + esc(e.military_area) + '</span></div>' : '') +
      (e.munitions_area ? '<div class="row"><span class="k">' + esc(t('sb_munitions')) +
        '</span><span class="empty">' + esc(e.munitions_area) + '</span></div>' : '') +
      (e.nearest_wreck ? '<div class="row"><span class="k">' + esc(t('sb_wreck')) +
        '</span><span>' + esc(e.nearest_wreck.name) + ' · ' +
        Math.round(e.nearest_wreck.distance_m) + ' m</span></div>' : '') +
      (e.military_area ? '<p class="note">' + esc(t('sb_mil_note')) + '</p>' : '') +
      (e.nearest_wreck ? '<p class="note">' + esc(t('wreck_note')) + '</p>' : '') +
      (e.munitions_area ? '<p class="note">' + esc(t('munitions_note')) + '</p>' : '') +
      '</div>';
    return h;
}

/* Viento y ola de FMI en el punto de la alerta, y si explican el cangrejeo.
 *
 * `drift_explained` false es el caso interesante: el buque cangrejea CONTRA
 * donde empujan viento y ola, asi que el forzamiento no lo explica y queda
 * algo por explicar. Eso es lo que convierte IND-02 en evidencia. */
function renderForcing(p) {
  var box = document.getElementById('forcing-box'); if (!box) { return; }
  box.innerHTML = '<div class="block"><h4>' + esc(t('fo_h')) +
    '</h4><p class="note">' + esc(t('fo_loading')) + '</p></div>';
  var q = '/forcing?lat=' + p.lat + '&lon=' + p.lon +
    (p.heading_deg !== null && p.heading_deg !== undefined ? '&hdg=' + p.heading_deg : '') +
    (p.cog_deg !== null && p.cog_deg !== undefined ? '&cog=' + p.cog_deg : '');
  fetch(q).then(function (r) {
    if (!r.ok) { throw new Error('HTTP ' + r.status); }
    return r.json();
  }).then(function (d) {
    var f = d.forcing || {}, dr = d.drift;
    if (!Object.keys(f).length) {
      box.innerHTML = '<div class="block"><h4>' + esc(t('fo_h')) +
        '</h4><p class="note empty">' + esc(t('fo_nogrid')) + '</p></div>';
      return;
    }
    var cls = dr && dr.drift_explained === false ? ' caution'
            : dr && dr.drift_explained === true ? ' fusion' : '';
    var row = function (k, v) {
      return v === undefined || v === null ? '' :
        '<div class="row"><span class="k">' + esc(k) + '</span><span>' + esc(v) + '</span></div>';
    };
    box.innerHTML = '<div class="block' + cls + '"><h4>' + esc(t('fo_h')) + '</h4>' +
      row(t('fo_wind'), f.WindSpeedMS !== undefined
          ? f.WindSpeedMS + ' m/s ' + t('fo_from') + ' ' + f.WindDirection + '°' : null) +
      row(t('fo_wave'), f.SigWaveHeight !== undefined
          ? f.SigWaveHeight + ' m ' + t('fo_from') + ' ' + f.WaveDirection + '°'
            + (f.WavePeriod ? ', ' + f.WavePeriod + ' s' : '') : null) +
      (dr ? row(t('fo_crab'), dr.crab_deg + '° ' +
                 (dr.crab_deg >= 0 ? t('g_starboard') : t('g_port'))) +
            row(t('fo_rel_wind'), dr.wind_rel_deg !== null ? dr.wind_rel_deg + '°' : null) +
            row(t('fo_rel_wave'), dr.wave_rel_deg !== null ? dr.wave_rel_deg + '°' : null) +
            '<p class="fo-verdict">' + esc(
              dr.drift_explained === true ? t('fo_yes')
              : dr.drift_explained === false ? t('fo_no') : t('fo_maybe')) + '</p>' +
            '<p class="note">' + esc(dr.why) + '</p>'
          : '') +
      '<p class="note">' + esc(d.source) + ' · CC BY 4.0</p></div>';
  }).catch(function () {
    box.innerHTML = '<div class="block"><h4>' + esc(t('fo_h')) +
      '</h4><p class="note empty">' + esc(t('fo_off')) + '</p></div>';
  });
}

function showDetail(f) {
  var p = f.properties, e = p.evidence || {};
  var ex = explainFor(p.indicator);
  var note = nameNote(p.name);
  var stype = shipTypeText(p.ship_type);
  var h = '<div class="detail-bar">' +
    '<button class="xbtn big" id="d-back" title="' + esc(t('back')) + '">&times;</button>' +
    '<span class="detail-bar-t">' + esc(p.name || ('MMSI ' + p.mmsi)) + '</span>' +
    '</div>' +
    /* Las dos acciones que de verdad se usan, juntas y arriba. El historial
     * estaba enterrado a media pantalla y habia que buscarlo. */
    '<div class="btn-row">' +
      '<button class="btn" id="d-map">' + esc(t('show_on_map')) + '</button>' +
      (HIST && HIST[String(p.mmsi)]
        ? '<button class="btn primary js-vessel" data-mmsi="' + esc(p.mmsi) + '">' +
          esc(t('vessel_situation')) + ' &rarr;</button>' : '') +
    '</div>' +
    /* El recorte satelital es la respuesta a «¿se ve de verdad ese barco?».
     * Va arriba porque es lo que decide si la alerta vale algo. */
    (window.chipHtml ? chipHtml(p.lon, p.lat, p.ts_ms, 's1') : '') +
    fusionBlock(p, e) +
    seabedBlock(e);

  h += '<div class="detail-sub">' + esc(p.indicator) +
       (p.kind === 'exposure' ? ' · <span class="badge expo">exposure</span>' : '') +
       ' · MMSI ' + esc(p.mmsi) + (stype ? ' · ' + esc(stype) : '') + '</div>';

  /* Lo explicativo, plegado. Un operador que ya sabe que es un IND-04 no
   * necesita leerlo cada vez; quien no lo sabe lo tiene a un clic. La linea
   * de resumen va fuera para que se sepa que hay dentro sin abrirlo. */
  if (note || ex) {
    h += '<details class="explain"><summary>' +
      esc(ex ? ex.title : p.name) +
      '<span class="note"> · ' + esc(t('why_expand')) + '</span></summary>' +
      '<div class="inner">' +
      (note ? '<div class="block note-box"><h4>' + esc(p.name) + '</h4><p>' +
         esc(note) + '</p></div>' : '') +
      (ex ? '<div class="block"><h4>' + esc(t('what_is_this')) + '</h4><p>' +
         esc(ex.what) + '</p></div>' +
        '<div class="block"><h4>' + esc(t('why_flagged')) + '</h4><p>' +
         esc(ex.why) + '</p></div>' +
        '<div class="block caution"><h4>' + esc(t('what_it_means')) + '</h4><p>' +
         esc(ex.not) + '</p></div>' +
        '<p class="note">' + esc(ex.tech) + '</p>' : '') +
      '</div></details>';
  }

  if (p.ts_ms) {
    var ageNow = Date.now() - p.ts_ms;
    h += '<div class="block' + (ageNow > 6 * 3600e3 ? ' caution' : '') + '">' +
      '<h4>' + esc(t('freshness')) + '</h4>' +
      '<div class="row"><span class="k">' + esc(t('last_fix')) + '</span><span>' +
        fmtUTC(p.ts_ms) + '</span></div>' +
      '<div class="row"><span class="k">' + esc(t('lost_ago_k')) + '</span><span>' +
        fmtDur(ageNow) + '</span></div>' +
      (e.gap_min !== undefined ? '<div class="row"><span class="k">' +
        esc(t('gap_duration')) + '</span><span>' + e.gap_min + ' min</span></div>' : '') +
      '<details><summary>' + esc(t('what_it_means')) + '</summary><div class="inner">' +
      '<p class="note">' + esc(t('freshness_note')) + '</p></div></details></div>';
  }
  /* El forzamiento, solo donde decide. IND-02 marca un buque que apunta a un
   * sitio y navega a otro, y viento y ola producen exactamente ese angulo:
   * sin consultarlos la alerta es una sospecha, con ellos es una evidencia o
   * un descarte. Se pide al abrir la alerta, no antes: es una peticion por
   * alerta mirada, no por alerta existente. */
  h += '<div id="forcing-box"></div>';
  h += '<details><summary>' + esc(t('evidence')) + '</summary><div class="inner">' +
       evidenceRows(e) + '</div></details>';
  h += '<details><summary>' + esc(t('vessel')) + '</summary><div class="inner">' +
       table({ mmsi: p.mmsi, imo: p.imo, call_sign: p.call_sign,
               ship_type: p.ship_type, ship_type_text: stype || p.ship_type_text,
               destination: p.destination, draught_m: p.draught_m,
               sog_kn: p.sog_kn, cog_deg: p.cog_deg, heading_deg: p.heading_deg,
               't_ais': iso(p.ts_ms) }) + '</div></details>';
  h += '<details><summary>' + esc(t('read_more')) + '</summary><div class="inner">' +
       '<div class="row"><span class="k">score</span><span>' + esc(p.score) +
       '</span></div><div class="row"><span class="k">composite</span><span>' +
       esc(p.composite_score) + '</span></div>' +
       '<div class="note">fix keys: ' + esc(JSON.stringify(e.fix_keys)) + '</div>' +
       '</div></details>';

  var box = document.getElementById('detail');
  box.innerHTML = h;
  box.classList.add('on');
  /* El recorte se pinta despues de insertar el HTML: necesita su contenedor
   * en el DOM para montar los botones de pasada y de tamano. */
  box.querySelectorAll('.chip-box').forEach(function (c) { chipBind(c.id); });
  document.getElementById('list-view').style.display = 'none';
  document.getElementById('tab-alerts').scrollTop = 0;
  /* Se pasa la alerta entera, no solo el MMSI: el panel del buque tiene que
   * poder decir de que alerta viene y pintarse de su color. */
  box.querySelectorAll('.js-vessel').forEach(function (b) {
    b.addEventListener('click', function () { showVessel(b.dataset.mmsi, undefined, f); });
  });
  document.getElementById('d-back').addEventListener('click', hideDetail);
  document.getElementById('d-map').addEventListener('click', function () {
    var ll = [f.geometry.coordinates[1], f.geometry.coordinates[0]];
    map.setView(ll, 12);
  });
  if (p.indicator === 'IND-02') { renderForcing(p); }
  if (window.onAlertInspected) { window.onAlertInspected(p); }
}

map.on('popupopen', function (e) {
  var el = e.popup.getElement();
  if (!el) { return; }
  el.querySelectorAll('.js-detail').forEach(function (b) {
    b.addEventListener('click', function () {
      openDetailByMmsi(b.dataset.mmsi, b.dataset.ind);
    });
  });
  el.querySelectorAll('.js-vessel').forEach(function (b) {
    b.addEventListener('click', function () { showVessel(b.dataset.mmsi, undefined, null); });
  });
  /* Mostrar/ocultar la traza sin salir del popup: la accion mas pedida no
   * deberia exigir abrir el panel lateral. */
  el.querySelectorAll('.js-track').forEach(function (b) {
    b.addEventListener('click', function () {
      if (typeof histLayer !== 'undefined' && histLayer) {
        closeHistory(); b.textContent = t('show_history');
      } else {
        trackOnly(b.dataset.mmsi); b.textContent = t('hide_history');
      }
    });
  });
});

window.rerenderAlerts = function () {
  if (alertFeatures && alertFeatures.length) {
    renderOpsFilters();
    renderAlertList(visibleAlertFeatures());
  }
};

function hideDetail() {
  var box = document.getElementById('detail');
  box.classList.remove('on'); box.innerHTML = '';
  document.getElementById('list-view').style.display = '';
}

function openDetailByMmsi(mmsi, ind) {
  for (var i = 0; i < alertFeatures.length; i += 1) {
    var p = alertFeatures[i].properties;
    if (String(p.mmsi) === String(mmsi) && String(p.indicator) === String(ind)) {
      map.closePopup(); showTab('alerts'); showDetail(alertFeatures[i]); return;
    }
  }
}

function addAlerts(fc) {
  alertFeatures = fc.features;
  function mk(kind, radius) {
    return L.geoJSON(fc, {
      filter: function (f) { return f.properties.kind === kind; },
      pointToLayer: function (f, ll) {
        var p = f.properties;
        return L.circleMarker(ll, { radius: radius, color: sevRing(p), weight: 2,
          fillColor: sevColour(p), fillOpacity: 0.45 });
      },
      onEachFeature: function (f, l) { l.bindPopup(alertPopup(f.properties), { maxWidth: 340 }); }
    });
  }
  layers.alerts = mk('alert', 10).addTo(map);
  layers.exposure = mk('exposure', 5).addTo(map);
  renderAlertList(fc.features);
}

/* ------------------------------- cobertura AIS y restricciones del Báltico */
/* Dos capas que sólo existen porque el alcance pasó del golfo al Báltico.
 * La primera dice DÓNDE VEMOS; la segunda, QUIÉN PROHÍBE. Sin la primera, el
 * sur vacío se lee como «no pasa nada»; sin la segunda, la capa jurídica
 * sería finlandesa pretendiendo ser báltica. */
function addAisCoverage(fc) {
  layers.ais_coverage = L.geoJSON(fc, {
    style: { color: '#2dd4bf', weight: 0.6, opacity: 0.5,
             fillColor: '#0d9488', fillOpacity: 0.10 },
    onEachFeature: function (f, l) {
      l.bindPopup('<h4>' + esc(t('cov_h')) + '</h4>' +
        '<div class="row"><span class="k">' + esc(t('cov_fixes')) + '</span><span>' +
        f.properties.fixes + '</span></div>' +
        '<p class="note">' + esc(t('cov_note')) + '</p>', { maxWidth: 320 });
    }
  });
}

var MSP_COLOURS = { EE: '#60a5fa', DE: '#f472b6', LT: '#fbbf24', LV: '#a78bfa' };

function addMsp(fc) {
  layers.msp_restricted = L.geoJSON(fc, {
    style: function (f) {
      var p = f.properties;
      var c = MSP_COLOURS[p.country] || '#94a3b8';
      return { color: c, weight: p.bottom_impact_forbidden ? 2 : 1,
               opacity: 0.85, dashArray: p.bottom_impact_forbidden ? null : '5 4',
               fillColor: c, fillOpacity: 0.10 };
    },
    onEachFeature: function (f, l) {
      var p = f.properties;
      l.bindPopup('<h4>' + esc(p.use || t('msp_h')) + '</h4>' +
        '<div class="note">' + esc(p.country || '?') + ' · ' +
        esc(t('msp_sub')) + '</div>' +
        table({ forbidden: p.forbidden, restricted: p.restricted,
                allowed: p.allowed, priority: p.priority, plan: p.plan_id }) +
        (p.bottom_impact_forbidden
          ? '<p class="note"><b>' + esc(t('msp_bottom')) + '</b></p>' : '') +
        '<p class="note">' + esc(t('msp_note')) + '</p>', { maxWidth: 360 });
    }
  });
}

/* El hueco jurídico, dicho en voz alta. Qué ribereños tienen capa y cuáles
 * no, con el motivo. Va en Sources, junto a la salud del build. */
function renderAuthorities() {
  var box = document.getElementById('authorities'); if (!box) { return; }
  var a = ((manifest.stats || {}).authorities) || null;
  if (!a) { box.innerHTML = ''; return; }
  var reg = a.registry || [];
  var h = '<p class="note">' + esc(t('auth_note', {
    n: a.countries_wired, m: a.countries_total })) + '</p>';
  h += reg.map(function (r) {
    return '<div class="row"><span class="k">' +
      '<span class="cc ' + (r.wired ? 'on' : 'off') + '">' + esc(r.cc) + '</span> ' +
      esc(r.country) + '</span><span class="' + (r.wired ? 'ok' : 'empty') + '">' +
      esc(r.wired ? (r.authority || '').split('(')[0].trim() : t('auth_none')) +
      '</span></div>' +
      (r.note ? '<div class="note">' + esc(r.note) + '</div>' : ''); }).join('');
  box.innerHTML = h;
}

/* ------------------------------------------- fondo marino y zonas declaradas */
/* Tres capas que no dicen que pasa, sino DONDE pasa. Un buque de guerra
 * despacio dentro de un area de defensa nacional no es una anomalia; un
 * fondeo sobre un vertedero de municion es otra cosa muy distinta. */
function addWrecks(fc) {
  layers.wrecks = L.geoJSON(fc, {
    pointToLayer: function (f, ll) {
      var p = f.properties;
      if (p.is_submarine) {
        /* Los submarinos se marcan aparte: son tres en todo el golfo y son
         * justo lo que la gente busca cuando pregunta por submarinos. */
        return L.marker(ll, { icon: L.divIcon({ className: 'wreck-sub',
          html: '<svg viewBox="0 0 24 24" width="22" height="22">' +
            '<ellipse cx="11" cy="13" rx="9" ry="3.2" fill="#ffd166" ' +
            'stroke="#3a2a00" stroke-width="1.2"/>' +
            '<path d="M11 10 L11 5 M8 5 h6" stroke="#3a2a00" stroke-width="1.6" ' +
            'fill="none"/></svg>', iconSize: [22, 22], iconAnchor: [11, 13] }) });
      }
      return L.circleMarker(ll, { radius: p.dangerous ? 4 : 3,
        color: p.dangerous ? '#c2410c' : '#6b7280', weight: 1,
        fillColor: p.dangerous ? '#7c2d12' : '#374151', fillOpacity: 0.8 });
    },
    onEachFeature: function (f, l) {
      var p = f.properties;
      l.bindPopup('<h4>' + (p.is_submarine ? '⚓ ' : '') +
        esc(p.name || p.type || t('wreck')) + '</h4>' +
        '<div class="note">' + esc(p.wreck_cate || '') + '</div>' +
        table({ type: p.type, flag: p.flag, sunk: p.date_sunk,
                length_m: p.length, depth_m: p.depth, tonnage: p.tonnage,
                cargo: p.cargo, circumstances: p.circumstan }) +
        '<p class="note">' + esc(t('wreck_note')) + '</p>', { maxWidth: 320 });
    }
  });
}

/* «¿Por que esta area es especial?» tiene que contestarse en el propio popup.
 * EMODnet solo publica pais, tipo y superficie: eso dice QUE esta designada,
 * no QUE hay dentro. El inventario lo calcula build.py contra las capas que
 * ya existen, asi que cada linea de aqui es comprobable con los mismos
 * ficheros. */
function milWhy(p) {
  var w = p.why || {};
  var h = '';
  if (w.corridors && w.corridors.length) {
    h += '<div class="block"><h4>' + esc(t('mil_infra')) + '</h4>' +
      w.corridors.map(function (c) {
        return '<div class="row"><span class="k">' + esc(c.name) + '</span><span>' +
          esc([c.kind, c.operator].filter(Boolean).join(' · ') || '—') +
          '</span></div>'; }).join('') +
      '<p class="note">' + esc(t('mil_infra_note')) + '</p></div>';
  }
  var rows = '';
  var add = function (k, v) {
    if (v === null || v === undefined || v === '') { return; }
    rows += '<div class="row"><span class="k">' + esc(k) + '</span><span>' +
      esc(v) + '</span></div>';
  };
  add(t('mil_area'), p.area_km2 ? p.area_km2 + ' km²' : null);
  if (w.depth_m) { add(t('mil_depth'), w.depth_m.min + '–' + w.depth_m.max + ' m'); }
  if (w.wrecks) {
    add(t('mil_wrecks'), w.wrecks.count +
      (w.wrecks.submarines ? ' (' + w.wrecks.submarines + ' ' + t('mil_subs') + ')' : ''));
  }
  if (w.vessels_seen !== undefined) { add(t('mil_traffic'), w.vessels_seen); }
  if (rows) { h += '<div class="block">' + rows + '</div>'; }

  /* El dato incomodo, y el que mas vale: tener un cable estrategico dentro de
   * un area de defensa NO implica que fondear ahi este prohibido. Si sale
   * cero, la cobertura juridica no existe y conviene que se vea. */
  if (w.anchoring_bans_inside !== undefined) {
    var n = w.anchoring_bans_inside;
    var crit = (w.corridors && w.corridors.length) && n === 0;
    h += '<div class="block' + (crit ? ' caution' : '') + '"><h4>' +
      esc(t('mil_legal_cover')) + '</h4>' +
      '<div class="row"><span class="k">' + esc(t('mil_bans')) + '</span><span class="' +
        (n ? 'ok' : 'empty') + '">' + n + '</span></div>' +
      '<p class="note">' + esc(t(crit ? 'mil_gap' : 'mil_bans_note')) + '</p></div>';
  }
  return h;
}

function addMilitary(fc) {
  layers.military_areas = L.geoJSON(fc, {
    style: { color: '#60a5fa', weight: 1.2, opacity: 0.8, dashArray: '6 4',
             fillColor: '#1e3a8a', fillOpacity: 0.12 },
    onEachFeature: function (f, l) {
      var p = f.properties, lg = p.legal || {};
      l.bindPopup('<h4>' + esc(p.name) + '</h4>' +
        '<div class="note">' + esc(t('mil_why')) + '</div>' +
        milWhy(p) +
        '<div class="block"><h4>' + esc(t('provenance')) + '</h4>' +
        '<div class="row"><span class="k">' + esc(t('mil_designation')) +
          '</span><span>' + esc(p.type_1 || '—') + '</span></div>' +
        '<div class="row"><span class="k">' + esc(t('mil_published_by')) +
          '</span><span>EMODnet Human Activities</span></div>' +
        '<div class="row"><span class="k">' + esc(t('mil_origin')) +
          '</span><span>' + esc(p.country || '—') + '</span></div>' +
        (lg.instrument ? '<div class="row"><span class="k">' + esc(t('mil_instrument')) +
          '</span><span>' + esc(lg.instrument) + '</span></div>' : '') +
        (lg.note ? '<p class="note">' + esc(lg.note) + '</p>' : '') +
        '<div class="btn-row">' +
        (p.resource ? '<a class="btn" href="' + esc(p.resource) +
          '" target="_blank" rel="noopener">' + esc(t('official_source')) + '</a>' : '') +
        (lg.verify ? '<a class="btn" href="' + esc(lg.verify) +
          '" target="_blank" rel="noopener">' + esc(t('mil_statute')) + '</a>' : '') +
        '</div></div>' +
        '<p class="note">' + esc(t('milarea_note')) + '</p>', { maxWidth: 380 });
    }
  });
}

function addMunitions(fc) {
  layers.munitions = L.geoJSON(fc, {
    style: { color: '#ef4444', weight: 1.5, opacity: 0.9, dashArray: '2 3',
             fillColor: '#7f1d1d', fillOpacity: 0.22 },
    onEachFeature: function (f, l) {
      var p = f.properties;
      l.bindPopup('<h4>☠ ' + esc(p.name) + '</h4>' +
        table({ type: p.munition_type, source: p.infoprov, updated: p.thedate,
                dist_coast_m: p.dist_coast ? Math.round(p.dist_coast) : null }) +
        '<p class="note">' + esc(t('munitions_note')) + '</p>', { maxWidth: 320 });
    }
  }).addTo(map);
}

/* ------------------------------------------------- Global Fishing Watch */
/* GFW no da posiciones AIS: da COMPORTAMIENTO ya clasificado. Su valor aqui
 * es ser una segunda opinion independiente. Un GAP de GFW sobre el mismo
 * MMSI y el mismo intervalo que un IND-04 nuestro convierte una alerta que
 * dependia de nuestro umbral en una alerta corroborada por otro equipo con
 * otro modelo. No coincidir tambien dice algo, y por eso se pinta todo. */
var GFW_STYLE = {
  GAP:        { colour: '#ff4438', label: 'AIS gap (intentional)' },
  ENCOUNTER:  { colour: '#ffb000', label: 'Vessel-to-vessel encounter' },
  LOITERING:  { colour: '#7cc6fe', label: 'Loitering' },
  PORT_VISIT: { colour: '#9ad6a0', label: 'Port visit' },
  FISHING:    { colour: '#c084fc', label: 'Fishing' }
};
window.gfwFeatures = [];

function addGfw(fc) {
  window.gfwFeatures = fc.features || [];
  layers.gfw_events = L.geoJSON(fc, {
    pointToLayer: function (f, ll) {
      var st = GFW_STYLE[f.properties.event_type] || { colour: '#8899aa' };
      return L.circleMarker(ll, { radius: 8, color: st.colour, weight: 2,
        fillColor: st.colour, fillOpacity: 0.25, dashArray: '4 3' });
    },
    onEachFeature: function (f, l) {
      var p = f.properties;
      var st = GFW_STYLE[p.event_type] || { label: p.event_type };
      l.bindPopup('<h4>' + esc(p.name || ('MMSI ' + (p.mmsi || '?'))) + '</h4>' +
        '<div class="note">Global Fishing Watch · ' + esc(st.label) + '</div>' +
        table({ event: p.event_type, mmsi: p.mmsi, flag: p.flag,
                start: p.start, end: p.end, duration_h: p.duration_h }) +
        (p.detail ? table(p.detail) : '') +
        '<p class="note">' + esc(t('gfw_caveat')) + '</p>', { maxWidth: 320 });
    }
  });
  var cb = document.getElementById('gfw-layer');
  var note = document.getElementById('gfw-status');
  var meta = (manifest.layers || {}).gfw_events || {};
  if (note) {
    note.textContent = window.gfwFeatures.length
      ? t('gfw_have', { n: window.gfwFeatures.length, d: meta.window_days || '?' })
      : (meta.note || t('gfw_none'));
  }
  if (cb && !cb.dataset.bound) {
    cb.dataset.bound = '1';
    cb.disabled = !window.gfwFeatures.length;
    cb.addEventListener('change', function () {
      if (cb.checked) { layers.gfw_events.addTo(map); }
      else { map.removeLayer(layers.gfw_events); }
    });
  }
}

/* ------------------------------- rejilla 4wings: la linea base que faltaba */
/* Esto es el mapa de calor de la web de GFW, y la razon de traerlo no es
 * estetica. Todo indicador de este visor es ABSOLUTO: lento sobre un cable =
 * alerta, con un umbral que admitimos no calibrado. Una rejilla de presencia
 * da la otra mitad: cuanto trafico ve normalmente esa celda. Lo anomalo deja
 * de ser «por debajo de 5 nudos» y pasa a ser «seis veces su propia media»,
 * que es defendible delante de alguien que pregunte de donde sale el numero. */
var GFW_GRID_STYLE = {
  presence: { label: 'Vessel presence (all AIS)', hue: 190 },
  fishing:  { label: 'Apparent fishing effort',   hue: 150 },
  sar:      { label: 'SAR detections, no AIS match', hue: 20 }
};
window.gfwGrid = { max: {}, fc: null };

function gridColour(kind, v) {
  var mx = window.gfwGrid.max[kind] || 1;
  /* Escala logaritmica: el trafico por celda tiene cola larga y en lineal
   * todo queda del mismo color salvo el carril de Helsinki-Tallin. */
  var f = Math.log1p(Math.max(0, v)) / Math.log1p(mx);
  var st = GFW_GRID_STYLE[kind] || { hue: 200 };
  return 'hsl(' + st.hue + ',' + Math.round(45 + 45 * f) + '%,' +
         Math.round(26 + 38 * f) + '%)';
}

function addGfwGrid(fc) {
  window.gfwGrid.fc = fc;
  var mx = {};
  (fc.features || []).forEach(function (f) {
    var k = f.properties.grid, v = f.properties.value || 0;
    if (!(k in mx) || v > mx[k]) { mx[k] = v; }
  });
  window.gfwGrid.max = mx;

  layers.gfw_grid = L.geoJSON(fc, {
    style: function (f) {
      return { color: '#00000000', weight: 0, fillOpacity: 0.45,
               fillColor: gridColour(f.properties.grid, f.properties.value) };
    },
    onEachFeature: function (f, l) {
      var p = f.properties, k = p.grid;
      var st = GFW_GRID_STYLE[k] || { label: k };
      /* Como en la web de GFW: la celda cuenta quien estuvo, no solo cuanto. */
      var skip = ['grid', 'value', 'value_field'];
      var rows = {};
      Object.keys(p).forEach(function (kk) {
        if (skip.indexOf(kk) < 0) { rows[kk] = p[kk]; } });
      l.bindPopup('<h4>' + esc(st.label) + '</h4>' +
        '<div class="row"><span class="k">' + esc(p.value_field || t('gfw_grid_val')) +
          '</span><span>' + (Math.round(p.value * 100) / 100) + '</span></div>' +
        table(rows) +
        '<p class="note">Global Fishing Watch · CC BY-SA 4.0. ' +
        esc(t('gfw_caveat')) + '</p>', { maxWidth: 320 });
    }
  });

  var cb = document.getElementById('gfwgrid-layer');
  var note = document.getElementById('gfwgrid-status');
  var meta = (manifest.layers || {}).gfw_grid || {};
  if (note) {
    note.textContent = (fc.features || []).length
      ? t('gfwgrid_have', { n: fc.features.length,
                            k: Object.keys(mx).join(', ') })
      : (meta.note || t('gfw_none'));
  }
  if (cb && !cb.dataset.bound) {
    cb.dataset.bound = '1';
    cb.disabled = !(fc.features || []).length;
    cb.addEventListener('change', function () {
      if (cb.checked) { layers.gfw_grid.addTo(map); layers.gfw_grid.bringToBack(); }
      else { map.removeLayer(layers.gfw_grid); }
    });
  }
}

/* Corroboracion: evento GFW del mismo MMSI que solapa el instante de la
 * alerta, con una holgura de una hora a cada lado. */
function gfwMatch(mmsi, tsMs) {
  if (!tsMs) { return null; }
  var slack = 3600e3;
  for (var i = 0; i < window.gfwFeatures.length; i += 1) {
    var p = window.gfwFeatures[i].properties;
    if (String(p.mmsi) !== String(mmsi)) { continue; }
    var a = (p.ts_ms || 0) - slack, b = (p.end_ms || p.ts_ms || 0) + slack;
    if (tsMs >= a && tsMs <= b) { return p; }
  }
  return null;
}

function addScenes(fc) {
  /* El catalogo propio solo pinta las huellas. La imagen la sirve
   * imagery.js, que pide su propio catalogo acotado a la vista. */
  if (window.initImagery) { initImagery(); }
  layers.scenes = L.geoJSON(fc, {
    /* Ambar y trazo grueso: esta capa se dibuja ENCIMA del mosaico SAR, que
     * es gris, y en gris tenue desaparecia. Es la capa de procedencia de la
     * ESA; si no se ve, no sirve de nada tenerla. */
    style: function (f) {
      var hit = f.properties.ais_vessels_in_footprint_pm30min;
      return { color: hit ? '#ffb02e' : '#8fa6ba', weight: hit ? 2.5 : 1.5,
               opacity: 0.95, dashArray: '7 5',
               fillColor: '#ffb02e', fillOpacity: hit ? 0.06 : 0.02 };
    },
    onEachFeature: function (f, l) {
      var p = f.properties;
      /* Lo que hace util a esta capa NO es la huella: es cuantos buques decia
       * el AIS que habia dentro de ella en el momento de la adquisicion. Eso
       * estaba en el dato y el popup no lo enseñaba. */
      var nAis = p.ais_vessels_in_footprint_pm30min;
      l.bindPopup('<h4>' + esc(p.platform) + ' · ' + esc(p.product_type) + '</h4>' +
        '<div class="note">' + esc(t('scene_what')) + '</div>' +
        (nAis !== undefined && nAis !== null
          ? '<div class="block' + (nAis ? ' fusion' : '') + '">' +
            '<div class="row"><span class="k">' + esc(t('scene_ais')) +
              '</span><span class="' + (nAis ? 'ok' : 'empty') + '">' + nAis +
              '</span></div>' +
            '<p class="note">' + esc(t(nAis ? 'scene_ais_yes' : 'scene_ais_no')) +
            '</p></div>' : '') +
        table({ id: p.id, datetime: p.datetime, polarizations: p.polarizations,
                orbit: p.orbit_state + ' rel=' + p.relative_orbit,
                processing: p.processing_level,
                size_mb: p.product_size_bytes
                  ? Math.round(p.product_size_bytes / 1e6) : null }) +
        '<div class="note">' + esc(t('scene_two_cat')) + '</div>' +
        '<div class="note">Contains modified Copernicus Sentinel data</div>',
        { maxWidth: 360 });
    },
    /* Una etiqueta por escena: hora de adquisicion y cuantos buques AIS
     * habia dentro. Es el resumen de la capa sin tener que pulsar. */
    onEachLayer: null
  });
  /* Apagada por defecto. Son doce rectangulos que tapan medio Baltico y no
   * responden ninguna pregunta operativa: son procedencia, no observacion.
   * Quien la necesita la enciende en Layers. */
  layers.scenes.eachLayer(function (l) {
    var p = l.feature.properties;
    var n = p.ais_vessels_in_footprint_pm30min;
    var c = l.getBounds().getCenter();
    L.marker(c, { interactive: false, icon: L.divIcon({
      className: 'rtag scene', iconSize: null, iconAnchor: [0, 10],
      html: '<b>CDSE ' + esc((p.datetime || '').slice(11, 16)) + 'Z</b><span>' +
            (n === undefined || n === null ? '—' : n + ' AIS') + '</span>' }) })
      .addTo(layers.scenes);
  });
}

/* ------------------------------------------------------------ panel */

/* Barra permanente de alertas: ventana temporal e interruptor de
 * visualizacion. Estaba enterrada en la pestana Filters, que es el ultimo
 * sitio donde alguien la busca mientras mira el mapa. La ventana cambia lo
 * que se ve de forma drastica, asi que tiene que estar a la vista, no a dos
 * clics. */
var ALERT_WINDOWS = [[1, '1h'], [6, '6h'], [24, '24h'], [168, '7d'], [0, 'all']];
var ALERTS_VISIBLE = true;

/* Horas entre el ultimo dato del build y ahora. */
var BUILD_STALE_H = 6;

function buildAgeH(m) {
  var end = ((m || manifest).time || {}).dataset_end_ms;
  return end ? (Date.now() - end) / 3600e3 : 0;
}

function renderAlertBar() {
  var box = document.getElementById('alertbar'); if (!box) { return; }
  var cur = TIME_FILTER.on ? TIME_FILTER.windowMs / 3600e3 : 0;
  var seen = seenCount();
  box.innerHTML =
    '<div class="ab-row">' +
      '<label class="switch"><input type="checkbox" id="ab-show"' +
        (ALERTS_VISIBLE ? ' checked' : '') + '> <span>' +
        esc(t('ab_show')) + '</span></label>' +
      '<span class="note">' + esc(t('ab_seen', { s: seen.seen, n: seen.total })) +
      '</span>' +
    '</div>' +
    '<div class="ab-row"><span class="k">' + esc(t('ab_window')) + '</span>' +
      ALERT_WINDOWS.map(function (w) {
        return '<button class="btn ab-w' + (cur === w[0] ? ' primary' : '') +
          '" data-win="' + w[0] + '">' +
          (w[1] === 'all' ? esc(t('range_all')) : w[1]) + '</button>'; }).join('') +
    '</div>' +
    '<div class="btn-row">' +
      '<button class="btn' + (OPS.onlyUnseen ? ' primary' : '') + '" id="ab-unseen"' +
        (seen.seen ? '' : ' disabled title="' + esc(t('ab_none_seen')) + '"') + '>' +
        esc(t('ab_only_new')) + '</button>' +
      '<button class="btn" id="ab-reset"' +
        (seen.seen ? '' : ' disabled title="' + esc(t('ab_none_seen')) + '"') + '>' +
        esc(t('ab_mark_unseen')) + '</button>' +
    '</div>' +
    basinFilterNote('alerts');

  box.querySelectorAll('[data-win]').forEach(function (b) {
    b.addEventListener('click', function () {
      var v = +b.dataset.win;
      TIME_FILTER.on = v > 0;
      if (v > 0) { TIME_FILTER.windowMs = v * 3600e3; }
      var tfo = document.getElementById('tf-on'), tfw = document.getElementById('tf-win');
      if (tfo) { tfo.checked = v > 0; }
      if (tfw) { tfw.value = String(v); }
      refreshAlertViews();
    });
  });
  var sw = document.getElementById('ab-show');
  if (sw) { sw.addEventListener('change', function () {
    ALERTS_VISIBLE = sw.checked; refreshAlertViews(); }); }
  bindBasinClear(box);
  var un = document.getElementById('ab-unseen');
  if (un) { un.addEventListener('click', function () {
    OPS.onlyUnseen = !OPS.onlyUnseen;
    un.classList.toggle('primary', OPS.onlyUnseen);
    refreshAlertViews(); }); }
  var rs = document.getElementById('ab-reset');
  if (rs) { rs.addEventListener('click', function () {
    try { localStorage.removeItem('custody.seen'); } catch (e) {}
    SEEN = {};
    /* Si quedaba puesto «solo sin revisar», tras marcar todo sin leer el
     * filtro no sobra pero tampoco filtra nada; se suelta para que el estado
     * de los botones y el de la lista no se contradigan. */
    OPS.onlyUnseen = false;
    refreshAlertViews(); }); }
}

/* Vistas y sin ver. Lo ya revisado pasa a segundo plano y lo nuevo destaca:
 * en una lista de 663 alertas, saber que has mirado ya es la mitad del
 * trabajo. La marca la pone onAlertInspected al abrir el detalle. */
function alertSeenKey(p) { return p.mmsi + '|' + p.indicator; }
function isSeen(p) {
  var o = (typeof SEEN === 'object' && SEEN) || {};
  return !!o[alertSeenKey(p)];
}
function seenCount() {
  var vis = (window.alertFeatures || []).filter(function (f) {
    return f.properties.kind === 'alert'; });
  return { total: vis.length,
           seen: vis.filter(function (f) { return isSeen(f.properties); }).length };
}

function renderAlertList(rawFeats) {
  /* Lo no visto primero, conservando el criterio de orden elegido dentro de
   * cada grupo. Con cientos de alertas, lo que uno quiere es ver lo que
   * todavia no ha mirado, no volver a recorrer lo mismo. */
  var feats = sortAlerts(rawFeats);
  feats = feats.filter(function (f) { return !isSeen(f.properties); })
    .concat(feats.filter(function (f) { return isSeen(f.properties); }));
  var nA = feats.filter(function (f) { return f.properties.kind === 'alert'; }).length;
  var nE = feats.length - nA;
  document.getElementById('alert-count').innerHTML =
    t('alerts_count', { a: '<b>' + nA + '</b>', e: '<b>' + nE + '</b>' }) +
    ' · <span class="empty">' + esc(t('uncalibrated')) + '</span>';
  var h = '';
  feats.forEach(function (f, i) {
    var p = f.properties, e = p.evidence || {};
    var ex = explainFor(p.indicator);
    var bits = [];
    if (e.corridor) { bits.push(e.corridor + ' @ ' + Math.round(e.min_distance_m) + ' m'); }
    if (e.depth_m !== undefined && e.depth_m !== null) { bits.push(e.depth_m + ' m'); }
    if (e.sog_median_kn !== undefined) {
      bits.push('SOG ' + e.sog_p10_kn + '-' + e.sog_p90_kn + ' kn, ' +
                Math.round(e.duration_s / 60) + ' min');
    }
    if (e.divergence_median_deg !== undefined) { bits.push('COG-HDG ' + e.divergence_median_deg + 'deg'); }
    if (e.gap_min !== undefined) {
      bits.push('gap ' + e.gap_min + ' min (' + e.gap_state + ')');
      /* Lo que el lector pregunta de verdad no es cuanto duro el hueco, sino
       * cuanto hace que se perdio la posicion. */
      if (p.ts_ms) { bits.push(t('lost_ago', { d: fmtDur(Date.now() - p.ts_ms) })); }
    }
    var key = p.mmsi + '|' + p.indicator;
    var wasSeen = !!SEEN[key];
    h += '<div class="card sev-' + severityOf(p) + (wasSeen ? ' seen-card' : ' new-card') +
      '" data-i="' + i + '" tabindex="0" role="button">' +
      (wasSeen ? '<span class="seen">&#10003;</span>'
               : '<span class="newdot" title="' + esc(t('ab_unseen_one')) + '"></span>') +
      '<div class="ttl"><span class="badge sev-' + severityOf(p) + '">' +
        esc(sevLabel(p)) + '</span><span class="badge">' + esc(p.indicator) + '</span>' +
      esc(p.name || ('MMSI ' + p.mmsi)) +
      (p.service_craft_declared ? ' <span class="badge svc">service</span>' : '') + '</div>' +
      '<div class="meta">MMSI ' + p.mmsi + ' · ' +
        esc(shipTypeText(p.ship_type) || p.ship_type_text || 'type n/a') + '</div>' +
      (ex ? '<div class="ev">' + esc(ex.title) + '</div>' : '') +
      (bits.length ? '<div class="meta">' + esc(bits.join(' · ')) + '</div>' : '') +
      '</div>';
  });
  var sel = document.getElementById('alert-sort');
  if (sel && !sel.dataset.bound) {
    sel.dataset.bound = '1';
    sel.innerHTML = SORT_KEYS.map(function (k) {
      return '<option value="' + k + '"' + (k === CURRENT_SORT ? ' selected' : '') +
        '>' + esc(t('sort_' + k)) + '</option>'; }).join('');
    sel.addEventListener('change', function () {
      CURRENT_SORT = sel.value; renderAlertList(alertFeatures); });
  }
  var box = document.getElementById('alert-list');
  box.innerHTML = h || '<div class="note">' + esc(t('no_alerts')) + '</div>';
  var open = function (el) { showDetail(feats[+el.dataset.i]); };
  box.querySelectorAll('.card').forEach(function (el) {
    el.addEventListener('click', function () { open(el); });
    el.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); open(el); } });
  });
}

/* Las capas se agrupan y cada grupo dice de quien es el dato. Un jurado
 * pregunta «de donde sale esto» capa por capa, y tenerlo en la misma linea
 * que el interruptor evita la respuesta de memoria. */
/* Las capas se agrupan por ORIGEN antes que por tema, y la pregunta que
 * separa los dos bloques es una sola: ¿esto lo decidio esta herramienta, o es
 * el dato de otro dibujado tal cual? Mezclarlos deja al que mira sin saber
 * que puede citar como fuente y que es nuestro juicio. `own` manda sobre
 * todo lo demas; dentro, el tema.
 *
 * tracks y positions van en EXTERNAS a proposito aunque las ensamblemos
 * nosotros: lo que se dibuja son emisiones AIS de Fintraffic, no una
 * conclusion nuestra. coastline e isobaths van en PROPIAS por lo contrario:
 * son geometria que calculamos a partir del DTM, no un producto de EMODnet.
 */
/* ---------------------------------------- interferencia de la navegacion
 *
 * DOS CAPAS QUE MIDEN COSAS DISTINTAS, y la diferencia es el punto.
 *
 *   estaciones fijas  nivel del mar, cada 30 s, AHORA. Solo Finlandia.
 *   aeronaves         10 km de altura, agregado 24 h, 1-2 dias tarde. Cubre
 *                     todo el Baltico donde haya vuelos.
 *
 * Encenderlas juntas enseña el solape y los dos puntos ciegos a la vez, que
 * es la lectura util: donde solo mide una, la otra no esta confirmando nada.
 */
function addGnssStations(fc) {
  var col = { good: '#4caf6d', satisfactory: '#e0a33a', poor: '#e05c6e' };
  layers.gnss_stations = L.geoJSON(fc, {
    pointToLayer: function (f, ll) {
      var q = f.properties.quality;
      return L.circleMarker(ll, {
        radius: q === 'good' ? 5 : 8, weight: q === 'good' ? 1 : 2,
        color: col[q] || '#6b7c8c', fillColor: col[q] || '#6b7c8c',
        fillOpacity: q === 'good' ? 0.35 : 0.75
      });
    },
    onEachFeature: function (f, lyr) {
      var p = f.properties, w = p.worst_signal || {};
      lyr.bindPopup(
        '<h4>' + esc(p.name) + '</h4>' +
        '<div class="note">' + esc(t('gnss_station_sub', { t: p.tag })) + '</div>' +
        '<div class="row"><span class="k">' + esc(t('gnss_quality')) + '</span><span' +
          (p.quality === 'good' ? ' class="ok"' : ' class="empty"') + '>' +
          esc(t('gnss_q_' + (p.quality || 'nodata'))) + '</span></div>' +
        '<div class="row"><span class="k">' + esc(t('gnss_sats')) + '</span><span>' +
          p.visible_satellites + '</span></div>' +
        (w.signal
          ? '<div class="row"><span class="k">' + esc(t('gnss_worst')) + '</span><span>' +
            esc(w.signal) + ' · ' + (w.avg_cnr_db_hz === null ||
              w.avg_cnr_db_hz === undefined ? '-' : w.avg_cnr_db_hz.toFixed(1)) +
            ' dB-Hz</span></div>' : '') +
        '<p class="note">' + esc(t('gnss_measures')) + '</p>' +
        '<p class="note caution-note">' + esc(t('gnss_caveat')) + '</p>',
        { maxWidth: 320 });
    }
  });
}

function addGpsInterference(fc) {
  layers.gps_interference = L.geoJSON(fc, {
    style: function (f) {
      var fr = f.properties.fraction_degraded || 0;
      return { color: fr > 0.4 ? '#e05c6e' : '#e0a33a', weight: 1,
               fillOpacity: 0.12 + 0.5 * Math.min(1, fr), opacity: 0.6 };
    },
    onEachFeature: function (f, lyr) {
      var p = f.properties, n = p.aircraft_degraded + p.aircraft_good;
      lyr.bindPopup(
        '<h4>' + esc(t('gj_h')) + '</h4>' +
        '<div class="row"><span class="k">' + esc(t('gj_day')) + '</span><span>' +
          esc(p.day) + '</span></div>' +
        '<div class="row"><span class="k">' + esc(t('gj_frac')) + '</span><span>' +
          Math.round(100 * p.fraction_degraded) + '% (' + p.aircraft_degraded +
          ' / ' + n + ')</span></div>' +
        '<p class="note caution-note">' + esc(t('gj_agg')) + '</p>' +
        '<p class="note">' + esc(t('gj_caveat')) + '</p>',
        { maxWidth: 340 });
    }
  });
}

/* El contorno de lo que GPSJAM midio ese dia. Sin relleno y con trazo
 * discontinuo: no es un dato sobre el mar, es el borde de la mirada. Lo que
 * queda fuera no es «GPS bien», es «no se miro». */
function addGpsCoverage(fc) {
  layers.gps_interference_coverage = L.geoJSON(fc, {
    style: { color: '#e0a33a', weight: 1.4, opacity: 0.75, dashArray: '7 5',
             fill: false },
    onEachFeature: function (f, l) {
      var p = f.properties;
      l.bindPopup('<h4>' + esc(t('gjc_h')) + '</h4>' +
        '<div class="row"><span class="k">' + esc(t('gj_day')) + '</span><span>' +
          esc(p.day) + '</span></div>' +
        '<div class="row"><span class="k">' + esc(t('gjc_area')) + '</span><span>' +
          Math.round(p.area_observed_km2).toLocaleString() + ' km²  (' +
          Math.round(100 * p.aoi_fraction_observed) + '% ' + esc(t('gjc_of_aoi')) +
          ')</span></div>' +
        '<p class="note">' + esc(t('gjc_in')) + '</p>' +
        '<p class="note caution-note">' + esc(t('gjc_out')) + '</p>',
        { maxWidth: 340 });
    }
  });
}

/* Tema y fuente de cada capa del build viven en layerpanel.js (LP_THEMES,
 * LP_SOURCES y la tabla BUILD), junto al resto del catalogo. Aqui habia un
 * LAYER_GROUPS que solo conocia las del build: media clasificacion. */

/* Capas que llevan una linea propia bajo la casilla porque sin ella no se
 * entiende que son. Se mantiene corto: una frase. */
var LAYER_NOTES = { scenes: 'scenes_row_note', snapshot: 'snap_row_note',
                    aishub: 'ah_row_note' };

/* Las capas las agrupa y las pinta layerpanel.js, desde un catalogo unico.
 * Aqui habia un bucle de grupos propio que escribia en #layers-own y
 * #layers-ext; habia otro igual en marine.js y un tercero en emodnet.js. */
function renderLayers() {
  if (window.renderLayerPanel) { renderLayerPanel(); }
}

function renderLayerRows(defs) {
  var h = '';
  defs.forEach(function (d) {
    var lyr = layers[d[0]];
    if (!lyr) {
      if (window.LAZY_JOBS && window.LAZY_JOBS[d[0]]) {
        var st = (window.LAZY && LAZY[d[0]]) ? LAZY[d[0]].state : 'pending';
        h += '<label><input type="checkbox" data-layer="' + d[0] + '"> ' + esc(d[1]) +
             ' <span class="note">(' + esc(t('lazy_' + (st === 'loading' ? 'loading' : 'pending'))) +
             ')</span></label>';
      }
      return;
    }
    /* Se cuentan FEATURES, no hijos de Leaflet. Las capas que anaden una
     * etiqueta al mapa por elemento contaban el doble: el catalogo CDSE
     * decia «(24)» para doce escenas. */
    var n = 0, feats = 0;
    lyr.eachLayer(function (l) { n += 1; if (l.feature) { feats += 1; } });
    if (feats) { n = feats; }
    h += '<label><input type="checkbox" data-layer="' + d[0] + '"' +
         (map.hasLayer(lyr) ? ' checked' : '') + '> ' + esc(d[1]) +
         ' <span class="note">(' + n + ')</span></label>' +
         (LAYER_NOTES[d[0]]
           ? '<p class="note sub-opt">' + esc(t(LAYER_NOTES[d[0]])) + '</p>' : '');
  });
  return h;
}

/* --------------------------------------------- donde estan los buques
 *
 * UNA sola respuesta, y la gobierna el cursor temporal.
 *
 * Llegamos aqui quitando cosas. Habia tres capas: `live` (pedido a
 * digitraffic al vuelo), `snapshot` (en el instante del cursor, desde el
 * historial) y `positions` (ultima posicion conocida, fijada en el build).
 * Las tres resultaron ser la misma base de datos:
 *
 *   - liveFetch YA metia cada fix en HIST, que es lo que lee la instantanea.
 *     La capa en vivo era el ultimo punto de la misma linea temporal pintado
 *     otra vez con otro color.
 *   - `positions` era otro punto de esa linea: 884 de 1.207 marcadores caian
 *     exactamente encima del ultimo fix de la traza. Lo unico que aportaba de
 *     verdad eran 103 buques oidos UNA vez, que no llegan a tener traza; esos
 *     se siembran ahora en HIST como trazas de un punto
 *     (seedSingleFixVessels, time.js).
 *
 * Asi que no hay nada que elegir ni nada que sincronizar: el cursor dice el
 * instante y el mapa dibuja ese instante. «LIVE on» no es otra capa, es el
 * cursor enganchado al fix mas nuevo mientras se sondea cada 60 s.
 */

function bindLayerRows(box) {
  box.querySelectorAll('input[data-layer]').forEach(function (cb) {
    cb.addEventListener('change', function () {
      var k = cb.dataset.layer, lyr = layers[k];
      if (!lyr && window.LAZY_JOBS && window.LAZY_JOBS[k]) {
        cb.disabled = true;
        window.LAZY_JOBS[k]().then(function () {
          cb.disabled = false;
          if (cb.checked && layers[k]) { map.addLayer(layers[k]); }
        });
        return;
      }
      if (!lyr) { return; }
      if (cb.checked) { map.addLayer(lyr); } else { map.removeLayer(lyr); }
    });
  });
}

/* Salud del build. Vive en Sources porque responde a la misma pregunta:
 * de donde sale cada cosa y que falta. Lo que antes era una pestana Status
 * con un `ok` verde sin explicar ahora dice literalmente que significa: la
 * capa se construyo Y escribio datos. Lo util no es el verde sino el rojo con
 * su motivo, asi que lo que falta va arriba y sin plegar. */
/* El almacen declarado y lo que haya fuera de el. Lo rellena /sources/time. */
var STORES = { roots: [], strays: [] };

function renderHealth() {
  var box = document.getElementById('health'); if (!box) { return; }
  var L_ = manifest.layers || {};
  var bad = [], good = [];
  Object.keys(L_).forEach(function (k) {
    (L_[k].status === 'ok' ? good : bad).push(k);
  });
  /* DONDE ESTAN LOS DATOS, dicho en la propia herramienta.
   *
   * Un sistema sano sabe donde vive su informacion y avisa cuando aparece
   * fuera de ahi. Leerla por detras --- que es lo que hacia antes-- arregla
   * el sintoma y deja el problema: dos almacenes creciendo a la vez sin que
   * nadie lo note. */
  var h = (STORES.roots.length ? '<div class="row"><span class="k">' +
      esc(t('health_store')) + '</span><span class="mono">' +
      esc(STORES.roots.join(' + ')) + '</span></div>' : '') +
    (STORES.strays.length ? '<div class="block caution"><b>' +
      esc(t('health_stray')) + '</b>' + STORES.strays.map(function (x) {
        return '<div class="note mono">' + esc(x.path) + '</div>' +
          (x.active ? '<div class="note"><b>' + esc(t('health_stray_live')) +
            '</b></div>' : '') +
          '<div class="note">' + esc(t('health_stray_fix', { p: x.path })) + '</div>';
      }).join('') + '</div>' : '') +
    '<div class="row"><span class="k">' + esc(t('health_built')) + '</span><span>' +
      esc(manifest.built_utc) + '</span></div>' +
    '<div class="row"><span class="k">AOI</span><span class="mono">' +
      esc((manifest.aoi || []).join(', ')) + '</span></div>' +
    '<div class="row"><span class="k">' + esc(t('health_layers')) + '</span><span>' +
      '<span class="ok">' + good.length + ' ' + esc(t('health_withdata')) + '</span>' +
      (bad.length ? ' · <span class="empty">' + bad.length + ' ' +
        esc(t('health_without')) + '</span>' : '') + '</span></div>' +
    '<p class="note">' + esc(t('health_note')) + '</p>';

  if (bad.length) {
    h += '<div class="block caution"><b>' + esc(t('health_missing')) + '</b>' +
      bad.map(function (k) {
        return '<div class="row"><span class="k">' + esc(k) + '</span><span class="empty">' +
          esc(L_[k].status) + '</span></div><div class="note">' +
          esc(L_[k].note || '-') + '</div>'; }).join('') + '</div>';
  }
  h += '<details><summary>' + esc(t('health_all')) + '</summary><div class="inner">' +
    good.map(function (k) {
      var v = L_[k];
      return '<div class="row"><span class="k">' + esc(k) + '</span><span class="ok">' +
        esc(v.status) + '</span></div>' +
        (v.note ? '<div class="note">' + esc(v.note) + '</div>' : ''); }).join('') +
    '</div></details>';
  box.innerHTML = h;
  var lic = document.getElementById('licences');
  if (lic) { lic.innerHTML = table(manifest.licences); }
}

/* Barra de actividad al estilo del editor: un icono por seccion. Pulsar el
 * icono ya activo PLIEGA la barra lateral, que es como se recupera pantalla
 * de mapa sin perder de vista donde estabas. Ctrl+B hace lo mismo. */
var CUR_TAB = 'alerts';

function panelCollapsed() { return document.body.classList.contains('panel-off'); }

function setPanel(open) {
  document.body.classList.toggle('panel-off', !open);
  var b = document.getElementById('panel-hide');
  if (b) { b.innerHTML = open ? '&#x2039;' : '&#x203a;'; }
  /* Leaflet recalcula su tamano al cambiar el contenedor; sin esto la mitad
   * del mapa queda gris hasta el siguiente gesto. Y como lo que se mueve es
   * el BORDE IZQUIERDO, invalidateSize ancla arriba a la izquierda y la
   * escena se desplaza: hay que volver a centrar donde estabas mirando. */
  if (window.map) { recenterAfterResize(); }
}

function recenterAfterResize() {
  var c = map.getCenter(), z = map.getZoom();
  setTimeout(function () {
    map.invalidateSize({ animate: false });
    map.setView(c, z, { animate: false });
  }, 200);
}

function showTab(name, fromRail) {
  /* La pestana Status se repartio: salud de build y licencias a Sources,
   * umbrales a Filters. El enlace antiguo sigue llevando a algun sitio. */
  if (name === 'status') { name = 'sources'; }
  if (!document.getElementById('tab-' + name)) { return; }
  if (fromRail && name === CUR_TAB && !panelCollapsed()) { setPanel(false); return; }
  CUR_TAB = name;
  setPanel(true);
  document.querySelectorAll('#activitybar button').forEach(function (x) {
    x.classList.toggle('on', x.dataset.tab === name); });
  document.querySelectorAll('.tab').forEach(function (x) { x.classList.remove('on'); });
  document.getElementById('tab-' + name).classList.add('on');
  var title = document.querySelector('#activitybar button[data-tab="' + name + '"]');
  var st = document.getElementById('section-title');
  if (st && title) { st.textContent = title.textContent.trim(); }
  if (location.hash.slice(1) !== name) { history.replaceState(null, '', '#' + name); }
}
document.querySelectorAll('#activitybar button').forEach(function (b) {
  b.addEventListener('click', function () { showTab(b.dataset.tab, true); });
});
document.getElementById('panel-hide').addEventListener('click', function () {
  setPanel(panelCollapsed());
});
document.addEventListener('keydown', function (e) {
  if ((e.ctrlKey || e.metaKey) && (e.key === 'b' || e.key === 'B')) {
    e.preventDefault(); setPanel(panelCollapsed());
  }
});

/* Asa de redimensionado. El ancho se recuerda en el navegador, como el resto
 * de preferencias de presentacion. */
(function () {
  var rz = document.getElementById('resizer');
  if (!rz) { return; }
  var KEY = 'custody.panelw';
  try {
    var saved = parseInt(localStorage.getItem(KEY), 10);
    if (saved >= 280 && saved <= 900) {
      document.documentElement.style.setProperty('--panel-w', saved + 'px');
    }
  } catch (e) {}
  var drag = function (ev) {
    var rail = parseInt(getComputedStyle(document.documentElement)
                 .getPropertyValue('--rail-w'), 10) || 54;
    var w = Math.max(280, Math.min(900, ev.clientX - rail));
    document.documentElement.style.setProperty('--panel-w', w + 'px');
  };
  var stop = function () {
    document.body.classList.remove('resizing');
    document.removeEventListener('mousemove', drag);
    document.removeEventListener('mouseup', stop);
    try {
      localStorage.setItem(KEY, parseInt(getComputedStyle(document.documentElement)
        .getPropertyValue('--panel-w'), 10));
    } catch (e) {}
    if (window.map) { recenterAfterResize(); }
  };
  rz.addEventListener('mousedown', function (ev) {
    ev.preventDefault();
    document.body.classList.add('resizing');
    document.addEventListener('mousemove', drag);
    document.addEventListener('mouseup', stop);
  });
}());
/* Deep link: index.html#status abre la pestana de Estado directamente. Sirve
 * para ensenar en el hackaton "que capas estan vacias y por que" sin clicar. */
window.addEventListener('hashchange', function () { showTab(location.hash.slice(1)); });
showTab(location.hash ? location.hash.slice(1) : 'alerts');

/* capas de red, explicitas y apagadas por defecto */
var osmTiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  { maxZoom: 18, opacity: 0.55, attribution: '(c) OpenStreetMap contributors' });
var emodnetWms = L.tileLayer.wms('https://ows.emodnet-bathymetry.eu/wms',
  { layers: 'emodnet:mean', styles: 'rainbowcolour', format: 'image/png',
    transparent: true, opacity: 0.45, version: '1.3.0',
    attribution: 'EMODnet Bathymetry' });
document.getElementById('osm-tiles').addEventListener('change', function (e) {
  if (e.target.checked) { osmTiles.addTo(map).bringToBack(); } else { map.removeLayer(osmTiles); }
});
/* La capa WMS pintaba el mar de rojo y verde sin decir que significaba. La
 * leyenda la publica el propio servicio por GetLegendGraphic, asi que se
 * muestra la OFICIAL, no una reinventada aqui.
 *
 * Y hay que decir lo que la leyenda revela: la rampa va de -6000 m a 0 y el
 * Baltico entero es mas somero que 460 m, asi que todo el mar cae en el
 * extremo rojo-verde de la escala. No es un fallo de pintado: es una paleta
 * calibrada para oceano abierto usada en un mar poco profundo. Para leer
 * profundidad en el Baltico sirven las isobatas propias, que estan cortadas
 * a 20/50/80/100 m. */
var EMODNET_LEGEND =
  'https://ows.emodnet-bathymetry.eu/wms?service=WMS&version=1.3.0' +
  '&request=GetLegendGraphic&layer=emodnet:mean&style=rainbowcolour' +
  '&format=image/png';

function renderWmsLegend(on) {
  var box = document.getElementById('wms-legend'); if (!box) { return; }
  if (!on) { box.innerHTML = ''; box.hidden = true; return; }
  box.hidden = false;
  var url = (window.PROXY && PROXY.on)
    ? '/cache/img?u=' + encodeURIComponent(EMODNET_LEGEND) : EMODNET_LEGEND;
  box.innerHTML = '<div class="wmsleg">' +
    '<img src="' + esc(url) + '" alt="EMODnet depth scale">' +
    '<div class="wmsleg-txt">' +
      '<div class="k">' + esc(t('wms_h')) + '</div>' +
      '<p class="note">' + esc(t('wms_note')) + '</p>' +
      '<p class="note empty">' + esc(t('wms_baltic')) + '</p>' +
    '</div></div>';
}

document.getElementById('depthmap').addEventListener('change', function (e) {
  if (window.depthMapOn) { depthMapOn(e.target.checked); }
});
document.getElementById('coasthd').addEventListener('change', function (e) {
  if (window.coastHdOn) { coastHdOn(e.target.checked); }
});
/* Se pide al terminar de mover, no durante: arrastrar el mapa no puede
 * disparar una peticion por fotograma. */
map.on('moveend', function () { if (window.coastRefresh) { coastRefresh(); } });

document.getElementById('emodnet-wms').addEventListener('change', function (e) {
  if (e.target.checked) { emodnetWms.addTo(map).bringToBack(); } else { map.removeLayer(emodnetWms); }
  renderWmsLegend(e.target.checked);
});

/* La leyenda la pinta ui.js (renderLegend), que conoce el idioma activo. */

/* ------------------------------------------------------------ arranque */

loadDepth().then(function () { return j('data/manifest.json'); }).then(function (m) {
  manifest = m;
  setAoi(m.aoi);
  map.fitBounds(AOI, { padding: [20, 20] });
  /* El dossier de buques se carga aparte y antes: la lista de buques y los
   * popups lo consultan en cuanto se pintan. Si falla, el visor sigue: VINFO
   * queda vacio y las fichas vuelven a lo que ya mostraban. */
  var viFile = (m.layers || {}).vessel_info;
  var viLoad = (viFile && viFile.file)
    ? j('data/' + viFile.file).then(function (d) { VINFO = d || {}; })
        .catch(function (e) { console.warn('vessel_info', e); })
    : Promise.resolve();
  /* La EDAD del build, no solo su fecha. Un build de hace dos dias deja la
   * pista de cobertura vacia por la derecha, y eso se lee como «se han
   * perdido datos» cuando lo que pasa es que la grabadora siguio y el build
   * no. Paso: 42 h de desfase y 115.617 registros grabados que el visor no
   * habia visto nunca. */
  var bAge = buildAgeH(m);
  var el = document.getElementById('built');
  el.textContent = 'build ' + m.built_utc + ' · AOI ' + m.aoi.join(', ');
  el.classList.toggle('stale', bAge > BUILD_STALE_H);
  if (bAge > BUILD_STALE_H) {
    el.textContent += ' · ' + t('build_stale', { h: Math.round(bAge) });
  }
  var st = m.stats || {};
  var th = (st.indicators || {});
  document.getElementById('thresholds').innerHTML =
    '<pre>' + esc(JSON.stringify(th.by_indicator || {}, null, 1)) + '</pre>' +
    '<div class="note">Full thresholds and their justification: ' +
    'custody/indicators.py (THRESHOLDS, JUSTIFICATION). Marked NOT CALIBRATED.</div>' +
    '<pre>' + esc(JSON.stringify(st.ais || {}, null, 1)) + '</pre>';
  renderHealth();
  renderAuthorities();

  var load = function (file, fn) {
    if (!file) { return Promise.resolve(); }
    return j('data/' + file).then(fn).catch(function (e) { console.warn(file, e); });
  };
  var L_ = m.layers;
  return Promise.all([
    viLoad,

    j('data/' + L_.corridors.file).then(function (r) { addCorridors(r, null); }),
    /* Las subcuencas antes del resto: clasifican buques y alertas, asi que
     * si llegan tarde el primer pintado filtra con una lista vacia. */
    (L_.marine && L_.marine.file
      ? j('data/' + L_.marine.file).then(loadMarine).catch(function () {})
      : Promise.resolve()),
    /* EMODnet: la linea base de trafico del AOI entero. Apagada por defecto
     * --- es fondo, y encenderla sola taparia el mapa-- pero cargada, porque
     * su catalogo alimenta tambien el carril de la linea de tiempo. */
    (L_.emodnet && L_.emodnet.file
      ? j('data/' + L_.emodnet.file).then(loadEmodnet).catch(function () {})
      : Promise.resolve()),
    load(L_.aishub && L_.aishub.file, addAisHub),
    j('data/basins.geojson').then(loadBasins).catch(function () {
      console.warn('sin basins.geojson: el foco por cuenca queda desactivado');
    }),


    load(L_.tracks && L_.tracks.file, addTracks),
    load(L_.positions && L_.positions.file, addPositions),
    load(L_.sentinel1 && L_.sentinel1.file, addScenes),
    load(L_.alerts && L_.alerts.file, addAlerts),
    load(L_.suppressed && L_.suppressed.file, addSuppressed),
    load(L_.gfw_events && L_.gfw_events.file, addGfw),
    load(L_.gfw_grid && L_.gfw_grid.file, addGfwGrid),
    load(L_.munitions && L_.munitions.file, addMunitions),
    load(L_.ais_coverage && L_.ais_coverage.file, addAisCoverage),
    load(L_.msp_restricted && L_.msp_restricted.file, addMsp),
    load(L_.gnss_stations && L_.gnss_stations.file, addGnssStations),
    load(L_.gps_interference_coverage && L_.gps_interference_coverage.file,
         addGpsCoverage),
    load(L_.gps_interference && L_.gps_interference.file, addGpsInterference)
  ]);
}).then(function () {
  renderLayers();
  renderOpsFilters();
  /* La costa se pide al abrir, por recuadros, y la cachea el proxy. Antes se
   * horneaba en el build Y ademas se pedia al navegar: el mismo dato dos
   * veces, en disco y por red. */
  /* Las alertas en vivo: el motor del servidor corre los siete indicadores
   * cada 60 s y empuja por SSE. Sin servidor propio esto falla en silencio y
   * se sigue con las del build, que es lo correcto. */
  if (window.liveAlertsStart) { liveAlertsStart(); }
  var ch = document.getElementById('coasthd');
  if (ch && window.coastHdOn) { ch.checked = true; coastHdOn(true); }
  if (window.renderBasinBar) { renderBasinBar(); }
  if (layers.alerts) { layers.alerts.bringToFront(); }
  if (tracksFc && window.initTime) {
    initTime(manifest, tracksFc);
    renderLayers();
    /* Arrancar en vivo. Lo primero que alguien quiere saber al abrir esto es
     * que esta pasando AHORA, no como estaba el mundo cuando se compilo. Va
     * detras de initTime porque liveOn mueve el cursor temporal y necesita la
     * linea de tiempo ya montada. Si la red falla, liveFetch lo dice en la
     * cabecera y el visor sigue sirviendo el build. */
    setTimeout(function () { if (window.liveOn && !LIVE.on) { liveOn(); } }, 400);
  }
  if (window.renderSources) { renderSources(); renderSourceStrip(); }
  /* El panel de capas, al final: su catalogo se arma de los tres sitios que
   * acaban de cargarse (build, Copernicus Marine, EMODnet). */
  if (window.lpInit) { lpInit(); }
  /* Lo pesado llega despues: 6,9 MB de restricciones y 1,5 de corredores
   * secundarios no pueden bloquear el primer pintado. Se descargan en
   * segundo plano, con barra de progreso, y se pueden pedir antes
   * encendiendo su capa. */
  var LM = manifest.layers;
  var jobs = [
    ['ports', LM.ports, addPorts],
    ['isobaths', LM.bathymetry, addIsobaths],
    ['corridors_other', LM.corridors_other, function (fc) { addCorridorsOther(fc); }],
    ['restrictions', LM.restrictions, addRestrictions],
    ['wrecks', LM.wrecks, addWrecks],
    ['military_areas', LM.military_areas, addMilitary]
  ].filter(function (x) { return x[1] && x[1].file; });
  window.LAZY_JOBS = {};
  jobs.forEach(function (x) {
    window.LAZY_JOBS[x[0]] = function () { return lazyLoad(x[0], x[1].file, x[2]); };
  });
  prefetchIdle(jobs.map(function (x) { return window.LAZY_JOBS[x[0]]; }));
}).catch(function (e) {
  document.getElementById('alert-list').innerHTML =
    '<div class="empty">Load failed: ' + esc(e.message) +
    '<br>Are you serving with <code>python3 -m http.server</code> from viewer/?</div>';
});
