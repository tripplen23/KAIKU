/* time.js - what instant is on screen, and letting the reader move it.
 *
 * Two facts drive the design:
 *   1. The store is NOT continuous. Polling produced a handful of coverage
 *      windows inside a span of days. A slider that glides over the gaps would
 *      lie, so it snaps to windows and says when it is in one.
 *   2. "Last known position" is not "position now". Outside a coverage window
 *      every marker is stale, and by how much is shown explicitly.
 *
 * Vessel history comes from the per-vertex `times` written by build.py. */
'use strict';

var TIME = { win: [], t0: 0, t1: 0, now: 0, built: 0, cursor: null,
             playing: false, timer: null, staleMs: 30 * 60 * 1000,
             /* Extremos del deslizador. Por defecto las ultimas 24 h: el
              * intervalo completo son dias de hueco y el control resultaba
              * inutil. v0/v1 son la vista; t0/t1 el dato. */
             v0: 0, v1: 0, viewMs: 24 * 3600e3 };
var HIST = {};          /* mmsi -> [{t, lon, lat, sog}] ordered */
var snapLayer = null;
var histLayer = null;

/* TZ.offsetMin es null = UTC (por defecto). Un numero = minutos sobre UTC.
 *
 * Por defecto UTC y con la Z a la vista a proposito: el AIS viaja en UTC, las
 * adquisiciones Sentinel estan en UTC y un informe de incidente se escribe en
 * UTC. Mostrar hora local sin decirlo es como se cometen los errores de dos
 * horas al correlacionar. Pero leer el reloj de pared tambien es trabajo, asi
 * que se puede cambiar: lo que no se puede es no saber cual se esta viendo,
 * por eso la etiqueta (Z / +02:00) va SIEMPRE pegada a la hora. */
var TZ = { offsetMin: null, label: 'Z' };

function tzApply(ms) {
  return TZ.offsetMin === null ? ms : ms + TZ.offsetMin * 60000;
}

function tzLabel() {
  if (TZ.offsetMin === null) { return 'Z'; }
  var m = TZ.offsetMin, sg = m < 0 ? '-' : '+';
  m = Math.abs(m);
  return sg + String(Math.floor(m / 60)).padStart(2, '0') + ':' +
         String(m % 60).padStart(2, '0');
}

function fmtUTC(ms) {
  if (!ms) { return '-'; }
  return new Date(tzApply(ms)).toISOString().replace('T', ' ').slice(0, 16)
         + tzLabel();
}

/* Redibuja todo lo que lleva una hora escrita. */
function tzSet(offsetMin) {
  TZ.offsetMin = offsetMin;
  try {
    if (offsetMin === null) { localStorage.removeItem(LS.tz); }
    else { localStorage.setItem(LS.tz, String(offsetMin)); }
  } catch (e) {}
  if (window.renderTimeBar && TIME.t1) { renderTimeBar(); }
  if (window.renderMapKey) { renderMapKey(); }
  if (window.refreshAlertViews) { refreshAlertViews(); }
}
function fmtDur(ms) {
  var s = Math.round(ms / 1000);
  if (s < 90) { return s + ' s'; }
  if (s < 5400) { return Math.round(s / 60) + ' min'; }
  if (s < 172800) { return (s / 3600).toFixed(1) + ' h'; }
  return (s / 86400).toFixed(1) + ' d';
}

/* ------------------------------------------------- history from tracks */
function buildHistory(fc) {
  HIST = {};
  fc.features.forEach(function (f) {
    var p = f.properties, segs = f.geometry.coordinates, ts = p.times || [],
        sg = p.sogs || [], hd = p.hdgs || [];
    var arr = [];
    segs.forEach(function (seg, i) {
      seg.forEach(function (c, k) {
        arr.push({ t: (ts[i] || [])[k] || null, lon: c[0], lat: c[1],
                   sog: (sg[i] || [])[k], hdg: (hd[i] || [])[k] });
      });
    });
    arr = arr.filter(function (x) { return x.t; })
             .sort(function (a, b) { return a.t - b.t; });
    if (arr.length) { HIST[String(p.mmsi)] = { name: p.name, ship_type: p.ship_type,
                                               destination: p.destination, pts: arr }; }
  });
  seedSingleFixVessels();
  return HIST;
}

/* -------------------------------------------- trazas en vivo -> HIST */
/* LO QUE QUITA DE EN MEDIO EL «HAY QUE COMPILAR OTRA VEZ».
 *
 * El build horneaba las trazas y el visor no tenia otra fuente, asi que todo
 * lo grabado despues existia en disco pero no en pantalla: la pista de
 * cobertura lo dibujaba hueco y el aviso decia, con razon, que no habia
 * buques ni alertas de ese tramo hasta recompilar.
 *
 * El motor del servidor ya construye esas trazas --- con el MISMO
 * ais.tracks_geojson() que el build--- sobre una ventana que llega justo
 * hasta el borde de lo compilado. Fusionarlas aqui, en el mismo HIST, hace
 * que el deslizador, la instantanea, el historial de un buque, los recuentos
 * y el foco por cuenca cubran tambien ese tramo. No hay dos modelos de buque:
 * hay uno, alimentado por dos fuentes.
 *
 * Deduplicado por marca de tiempo: build y motor se solapan a proposito --- el
 * motor pide medio hora de mas--- para que una derrota no pierda el fix
 * anterior al corte y con el su velocidad y su rumbo de entrada.
 */
var LIVEV = { at: 0, from: 0, vessels: 0, added: 0, newest: 0, err: null,
              /* El inicio de la ventana QUE EVALUA EL MOTOR, declarado por el
               * propio motor. No se deduce de los fixes recibidos: con la
               * grabadora parada el fix mas antiguo es posterior al inicio de
               * la ventana, y confundir las dos cosas hacia que un hueco de
               * GRABACION se anunciara como un hueco de evaluacion. */
              winStart: 0, capped: false };

function mergeLiveTracks(fc) {
  var added = 0, touched = 0, from = 0, newest = 0;
  (fc.features || []).forEach(function (f) {
    var p = f.properties, segs = f.geometry.coordinates, ts = p.times || [],
        sg = p.sogs || [], hd = p.hdgs || [];
    var m = String(p.mmsi);
    var cur = HIST[m];
    if (!cur) {
      cur = HIST[m] = { name: p.name, ship_type: p.ship_type,
                        destination: p.destination, pts: [] };
    } else if (!cur.name && p.name) {
      cur.name = p.name;
    }
    var have = {};
    cur.pts.forEach(function (x) { have[x.t] = 1; });
    var got = 0;
    segs.forEach(function (seg, i) {
      seg.forEach(function (c, k) {
        var tt = (ts[i] || [])[k];
        if (!tt || have[tt]) { return; }
        have[tt] = 1;
        cur.pts.push({ t: tt, lon: c[0], lat: c[1],
                       sog: (sg[i] || [])[k], hdg: (hd[i] || [])[k] });
        got += 1;
        if (!from || tt < from) { from = tt; }
        if (tt > newest) { newest = tt; }
      });
    });
    if (got) {
      cur.pts.sort(function (a, b) { return a.t - b.t; });
      cur.live = true;
      added += got; touched += 1;
    }
  });
  LIVEV.at = Date.now();
  LIVEV.vessels = (fc.features || []).length;
  LIVEV.added = added;
  /* El mas antiguo de TODO lo fusionado, no el de este lote: a partir de la
   * segunda vuelta se piden solo los ultimos 30 min. */
  if (from && (!LIVEV.from || from < LIVEV.from)) { LIVEV.from = from; }
  var pr = fc.properties || {};
  if (pr.window_start_ms) { LIVEV.winStart = pr.window_start_ms; }
  LIVEV.capped = !!pr.window_capped;
  if (newest) {
    LIVEV.newest = newest;
    /* El dato llega mas alla de donde termina el build: el extremo del
     * deslizador tiene que seguirlo, o el cursor no puede llegar hasta lo
     * ultimo que sabemos. */
    if (newest > TIME.t1) { TIME.t1 = newest; applyView(); }
  }
  LIVEV.err = null;
  return { vessels: LIVEV.vessels, added: added, touched: touched };
}

/* Buques oidos UNA sola vez. El constructor de trazas necesita dos puntos
 * para dibujar una linea, asi que estos no aparecen en tracks.geojson y
 * vivian solo en positions.geojson. Medido: 103 buques.
 *
 * Eran la unica razon real para tener una capa «ultima posicion» aparte, asi
 * que en vez de mantener una capa entera por ellos se meten en el historial
 * como trazas de un punto. Asi la linea temporal los cubre y la respuesta a
 * «donde esta cada buque» vuelve a ser una sola. */
function seedSingleFixVessels() {
  if (!window.positionsFc) { return 0; }
  var n = 0;
  positionsFc.features.forEach(function (f) {
    var p = f.properties, m = String(p.mmsi);
    if (HIST[m] || !p.ts_ms) { return; }
    HIST[m] = { name: p.name || null, ship_type: p.ship_type || null,
                destination: p.destination || null, single: true,
                pts: [{ t: p.ts_ms, lon: f.geometry.coordinates[0],
                        lat: f.geometry.coordinates[1],
                        sog: p.sog_kn, hdg: p.heading_deg }] };
    n += 1;
  });
  return n;
}

/* ------------------------------------------------- snapshot at instant */
function inWindow(at) {
  for (var i = 0; i < TIME.win.length; i += 1) {
    if (at >= TIME.win[i][0] && at <= TIME.win[i][1]) { return TIME.win[i]; }
  }
  return null;
}

function snapshotAt(at) {
  var out = [];
  Object.keys(HIST).forEach(function (m) {
    var pts = HIST[m].pts, n = pts.length;
    if (!n || pts[0].t > at) { return; }
    var lo = 0, hi = n - 1;
    while (lo < hi) {
      var mid = (lo + hi + 1) >> 1;
      if (pts[mid].t <= at) { lo = mid; } else { hi = mid - 1; }
    }
    var last = pts[lo];
    out.push({ mmsi: m, meta: HIST[m], fix: last, age: at - last.t });
  });
  return out;
}

function snapshotPopupHtml(r, stale) {
  return '<h4>' + esc(r.meta.name || ('MMSI ' + r.mmsi)) + '</h4>' +
    '<div class="note">MMSI ' + esc(r.mmsi) + ' · ' +
      esc(shipTypeText(r.meta.ship_type) || '') + '</div>' +
    '<div class="row"><span class="k">fix</span><span>' + fmtUTC(r.fix.t) + '</span></div>' +
    '<div class="row"><span class="k">age at cursor</span><span>' +
      (stale ? '<span class="empty">' + fmtDur(r.age) + '</span>' : fmtDur(r.age)) +
      '</span></div>' +
    '<div class="row"><span class="k">SOG</span><span>' +
      (r.fix.sog === null || r.fix.sog === undefined ? '-' : r.fix.sog + ' kn') + '</span></div>' +
    vesselCard(r.mmsi, r.meta.name, r.meta.ship_type, r.fix.lon, r.fix.lat,
               { sog_kn: r.fix.sog, heading_deg: r.fix.hdg });
}

function drawSnapshot(at) {
  if (snapLayer) { map.removeLayer(snapLayer); }
  /* Sin guardas: esta ES la vista de buques. Los marcadores van al <canvas>
   * (createShipMarker) y el HTML del popup se construye perezosamente solo al
   * pulsar un buque, evitando >1.000 nodos <svg> y >1.000 fichas HTML por
   * movimiento del cursor. */
  var rows = snapshotAt(at).filter(function (r) { return visibleOnMap(r.mmsi); });
  var fresh = 0;
  snapLayer = L.layerGroup();
  rows.forEach(function (r) {
    var stale = r.age > TIME.staleMs;
    if (!stale) { fresh += 1; }
    var hdg = r.fix.hdg === undefined ? null : r.fix.hdg;
    var mk = (window.createShipMarker
      ? createShipMarker([r.fix.lat, r.fix.lon], hdg,
                         stale ? '#44596d' : '#58d68d', stale ? 12 : 17, stale)
      : L.marker([r.fix.lat, r.fix.lon], {
          icon: shipIcon(hdg, stale ? '#44596d' : '#58d68d', stale ? 12 : 17, stale)
        })
    ).bindPopup(function () { return snapshotPopupHtml(r, stale); }, { maxWidth: 330 });
    mk._mkProps = { sog: r.fix.sog, heading: r.fix.hdg, mmsi: r.mmsi, stale: stale };
    mk.addTo(snapLayer);
  });
  snapLayer.addTo(map);
  layers.snapshot = snapLayer;
  if (window.renderMapKey) { renderMapKey(); }
  return { total: rows.length, fresh: fresh };
}


/* ----------------------------------------------------- Pathfinder view */
/* Vessel-centric history over a chosen range. The range buttons are the easy
 * half. The hard half is saying, for that exact range, how much of it we
 * actually hold: without that the view implies a continuous history it does
 * not have. */

var RANGES = [['24h', 24 * 3600e3], ['7d', 7 * 86400e3], ['30d', 30 * 86400e3],
              ['1y', 365 * 86400e3], ['all', null]];
var VESSEL_RANGE = 7 * 86400e3;

function coverageIn(a, b) {
  var cov = 0;
  TIME.win.forEach(function (w) {
    var lo = Math.max(a, w[0]), hi = Math.min(b, w[1]);
    if (hi > lo) { cov += hi - lo; }
  });
  return cov;
}

/* Clasificacion en caliente. Las facetas salen de vessel_info.json, que es
 * AIS puro salvo la marca de sanciones: tipo autodeclarado, eslora medida y
 * bandera deducida del MID. Nada de esto necesita red ni recompilar. */
/* `onMap` es lo que convierte esto de una lista filtrada en un instrumento:
 * lo marcado es lo VISIBLE, y el mapa obedece. Filtrar bandera Rusia y luego
 * «solo sancionados» deja en pantalla exactamente esos cascos y nada mas. */
var VFILTER = { fam: {}, size: {}, flag: {}, sanctioned: false, text: '',
                onMap: true };
/* Trazas de toda la seleccion a la vez. Es una capa aparte del historial de
 * un buque suelto: conviven. */
var FLEET = { layer: null, mmsis: [], capped: 0 };
var FLEET_CAP = 80;

/* UN solo predicado. Si la lista y el mapa usaran reglas distintas acabarian
 * discrepando, y un mapa que miente sobre lo que oculta es peor que uno sin
 * filtro. */
function vesselVisible(mmsi) {
  var m = String(mmsi);
  var vi = vinfo(m) || {}, c = vi.class || {};
  if (VFILTER.text) {
    var q = VFILTER.text.toLowerCase();
    var nm = (vi.name || (HIST[m] && HIST[m].name) || '').toLowerCase();
    if (m.indexOf(q) < 0 && nm.indexOf(q) < 0) { return false; }
  }
  if (VFILTER.sanctioned && !(vi.sanctions && vi.sanctions.length)) { return false; }
  if (VFILTER.fam[c.family || 'unknown'] === false) { return false; }
  if (c.size_class && VFILTER.size[c.size_class] === false) { return false; }
  if (VFILTER.flag[flagOf(m)] === false) { return false; }
  return true;
}

function vfilterActive() {
  if (VFILTER.sanctioned || VFILTER.text) { return true; }
  return ['fam', 'size', 'flag'].some(function (k) {
    return Object.keys(VFILTER[k]).some(function (x) { return VFILTER[k][x] === false; });
  });
}

/* Solo manda sobre el mapa si el interruptor esta puesto. Sin filtro activo
 * no se oculta nada, para que el estado por defecto sea «lo veo todo». */
function mapFilterOn() { return VFILTER.onMap && vfilterActive(); }
/* La cuenca enfocada se aplica a los buques igual que a las alertas: el
 * punto del foco es que lo de fuera deje de competir por la atencion. */
function inFocusedBasin(mmsi) {
  if (!window.BASIN || !BASIN.id) { return true; }
  var b = basinById(BASIN.id);
  if (!b) { return true; }
  var v = HIST[String(mmsi)];
  if (!v || !v.pts || !v.pts.length) { return true; }
  var p = v.pts[v.pts.length - 1];
  return inBasin(b, p.lon, p.lat);
}

/* El filtro de buques SIN la cuenca. opsPass() lo usa para decidir si pintar
 * la alerta de un casco oculto, y ahi la cuenca no debe entrar: una alerta
 * tiene posicion propia, y donde este AHORA el buque no cambia donde ocurrio.
 * Aplicar las dos la filtraba dos veces por criterios que no coinciden. */
function vesselPassesFilter(mmsi) {
  return !mapFilterOn() || vesselVisible(mmsi);
}

/* Para DIBUJAR un buque si manda la cuenca: el punto del foco es que lo de
 * fuera deje de ocupar el mapa. */
function visibleOnMap(mmsi) {
  return inFocusedBasin(mmsi) && vesselPassesFilter(mmsi);
}

function vesselList(filter) {
  var rows = Object.keys(HIST).map(function (m) {
    var v = HIST[m], vi = vinfo(m) || {};
    var c = vi.class || {}, d = vi.dimensions || {};
    return { mmsi: m, name: v.name || vi.name, ship_type: v.ship_type,
             n: v.pts.length, last: v.pts[v.pts.length - 1].t,
             span: v.pts[v.pts.length - 1].t - v.pts[0].t,
             family: c.family || 'unknown', size_class: c.size_class || null,
             length_m: d.length_m || null, flag: flagOf(m),
             sanctioned: !!(vi.sanctions && vi.sanctions.length) };
  });
  if (filter !== undefined && filter !== null) { VFILTER.text = filter; }
  rows = rows.filter(function (r) { return vesselVisible(r.mmsi) && inFocusedBasin(r.mmsi); });
  /* Un buque sancionado sube siempre: es el dato que no se puede perder en
   * una lista de quinientos. */
  rows.sort(function (a, b) {
    return (b.sanctioned - a.sanctioned) || (b.n - a.n) || (b.last - a.last); });
  return rows;
}

/* -------------------------------------- el filtro manda sobre el mapa */
function applyVesselFilter() {
  if (window.buildTracksLayer && tracksFc) { buildTracksLayer(); }
  if (TIME.t1) { drawSnapshot(TIME.cursor === null ? TIME.t1 : TIME.cursor); }
  if (typeof LIVE !== 'undefined' && LIVE.on && LIVE.last) { drawLive(LIVE.last); }
  if (FLEET.layer) { showFleetTracks(); }        /* la flota sigue al filtro */
  if (window.refreshAlertViews) { refreshAlertViews(); }
  renderFilterBanner();
}

/* Un mapa filtrado TIENE que decir que lo esta. Sin esto, alguien enseña una
 * pantalla con tres barcos y la sala entiende «hay tres barcos». */
function renderFilterBanner() {
  var el = document.getElementById('vfbanner');
  if (!el) { return; }
  if (!mapFilterOn()) { el.hidden = true; el.innerHTML = ''; return; }
  var total = Object.keys(HIST).length;
  var shown = Object.keys(HIST).filter(vesselVisible).length;
  el.hidden = false;
  var al = (window.visibleAlertFeatures ? visibleAlertFeatures() : [])
    .filter(function (f) { return f.properties.kind === 'alert'; }).length;
  el.innerHTML = '<span class="vfb-dot"></span>' +
    '<b>' + t('vfb_showing', { n: shown, m: total }) + '</b>' +
    '<b class="vfb-al">' + t('vfb_alerts', { n: al }) + '</b>' +
    '<span class="note">' + esc(filterSummary()) + '</span>' +
    '<button class="btn" id="vfb-zoom">' + esc(t('vfb_zoom')) + '</button>' +
    '<button class="btn' + (FLEET.layer ? ' primary' : '') + '" id="vfb-tracks">' +
      esc(FLEET.layer ? t('vfb_tracks_off') : t('vfb_tracks')) + '</button>' +
    '<button class="btn" id="vfb-clear">' + esc(t('vfb_clear')) + '</button>';
  document.getElementById('vfb-zoom').addEventListener('click', zoomToSelection);
  document.getElementById('vfb-tracks').addEventListener('click', function () {
    if (FLEET.layer) { clearFleetTracks(); } else { showFleetTracks(); }
    renderFilterBanner();
  });
  document.getElementById('vfb-clear').addEventListener('click', resetVesselFilter);
}

function filterSummary() {
  var bits = [];
  if (VFILTER.sanctioned) { bits.push(t('vf_sanctioned')); }
  if (VFILTER.text) { bits.push('"' + VFILTER.text + '"'); }
  ['fam', 'size', 'flag'].forEach(function (k) {
    var on = Object.keys(VFILTER[k]).filter(function (x) { return VFILTER[k][x] === false; });
    if (on.length) { bits.push(t('vf_' + (k === 'fam' ? 'type' : k)) + ' −' + on.length); }
  });
  return bits.join(' · ');
}

function resetVesselFilter() {
  VFILTER = { fam: {}, size: {}, flag: {}, sanctioned: false, text: '',
              onMap: VFILTER.onMap };
  clearFleetTracks();
  renderVesselTab('');
  applyVesselFilter();
}

function selectedMmsis() {
  return Object.keys(HIST).filter(vesselVisible);
}

function zoomToSelection() {
  var pts = [];
  selectedMmsis().forEach(function (m) {
    var p = HIST[m].pts;
    if (p.length) { pts.push([p[p.length - 1].lat, p[p.length - 1].lon]); }
  });
  if (!pts.length) { return; }
  map.fitBounds(L.latLngBounds(pts), { padding: [60, 60], maxZoom: 12 });
}

/* ------------------------------------ trazas de toda la seleccion */
/* Un color por casco, pero los sancionados SIEMPRE en rojo: el objetivo del
 * ejercicio es ver de un vistazo por donde se mueve lo que preocupa. */
function fleetColour(mmsi, i, n) {
  var vi = vinfo(mmsi);
  if (vi && vi.sanctions && vi.sanctions.length) { return '#ff3b2f'; }
  return 'hsl(' + Math.round(360 * i / Math.max(1, n)) + ',75%,62%)';
}

function showFleetTracks() {
  clearFleetTracks();
  var all = selectedMmsis();
  /* Con quinientas trazas encima no se ve nada: se recortan las de menos
   * posiciones y se dice cuantas quedaron fuera, en vez de dibujar una
   * maranya o callarse. */
  all.sort(function (a, b) {
    var sa = (vinfo(a) || {}).sanctions ? 1 : 0, sb = (vinfo(b) || {}).sanctions ? 1 : 0;
    return (sb - sa) || (HIST[b].pts.length - HIST[a].pts.length);
  });
  var use = all.slice(0, FLEET_CAP);
  FLEET.capped = all.length - use.length;
  FLEET.mmsis = use;
  FLEET.layer = L.layerGroup();
  use.forEach(function (m, i) {
    var pts = HIST[m].pts;
    if (pts.length < 2) { return; }
    var col = fleetColour(m, i, use.length);
    var ll = pts.map(function (x) { return [x.lat, x.lon]; });
    var vi = vinfo(m) || {};
    var san = !!(vi.sanctions && vi.sanctions.length);
    L.polyline(ll, { color: col, weight: san ? 3 : 2,
                     opacity: san ? 0.95 : 0.7 })
      .bindPopup('<h4>' + (san ? '⛔ ' : '') +
        esc(vi.name || HIST[m].name || ('MMSI ' + m)) + '</h4>' +
        '<div class="note">' + esc(flagOf(m)) + ' · ' + pts.length + ' ' +
        esc(t('positions').toLowerCase()) + '</div>' +
        '<div class="btn-row"><button class="btn primary js-vessel" data-mmsi="' +
        esc(m) + '">' + esc(t('vessel_situation')) + ' &rarr;</button></div>')
      .addTo(FLEET.layer);
    var last = pts[pts.length - 1];
    L.circleMarker([last.lat, last.lon], { radius: san ? 6 : 4, color: '#06101a',
      weight: 1.5, fillColor: col, fillOpacity: 1 }).addTo(FLEET.layer);
  });
  FLEET.layer.addTo(map);
  layers.fleet = FLEET.layer;
  zoomToSelection();
}

function clearFleetTracks() {
  if (FLEET.layer) { map.removeLayer(FLEET.layer); }
  FLEET.layer = null; FLEET.mmsis = []; FLEET.capped = 0;
  delete layers.fleet;
}

function vesselFacets() {
  var fam = {}, size = {}, flag = {}, san = 0;
  Object.keys(HIST).forEach(function (m) {
    var vi = vinfo(m) || {}, c = vi.class || {};
    var f = c.family || 'unknown';
    fam[f] = (fam[f] || 0) + 1;
    if (c.size_class) { size[c.size_class] = (size[c.size_class] || 0) + 1; }
    var fl = flagOf(m);
    flag[fl] = (flag[fl] || 0) + 1;
    if (vi.sanctions && vi.sanctions.length) { san += 1; }
  });
  return { fam: fam, size: size, flag: flag, sanctioned: san };
}

function facetHtml() {
  var f = vesselFacets();
  var group = function (key, title, counts, labels, order) {
    var ks = order ? order.filter(function (k) { return counts[k]; })
                   : Object.keys(counts).sort(function (a, b) {
                       return counts[b] - counts[a]; });
    if (!ks.length) { return ''; }
    /* Plegables salvo Tipo: doce banderas en abierto se comian media pantalla
     * y el buscador quedaba fuera de la vista. Un grupo con algun filtro
     * puesto se abre solo, para que no se olvide activo. */
    var dirty = ks.some(function (k) { return VFILTER[key][k] === false; });
    var open = (key === 'fam') || dirty;
    return '<details class="vfacet"' + (open ? ' open' : '') + '><summary>' +
      esc(title) + ' <span class="note">' + ks.length +
      (dirty ? ' · ' + t('vf_active') : '') + '</span></summary>' +
      '<div class="ops-chips">' + ks.map(function (k) {
        return '<label class="chipbox"><input type="checkbox" data-vf="' + key +
          '" data-k="' + esc(k) + '"' + (VFILTER[key][k] === false ? '' : ' checked') +
          '> ' + esc((labels && labels[k]) || k) + ' <span class="note">' +
          counts[k] + '</span></label>'; }).join('') + '</div></details>';
  };
  var sel = selectedMmsis().length, total = Object.keys(HIST).length;
  var h = '<div class="vf-head">' +
    '<label class="switch"><input type="checkbox" id="vf-onmap"' +
      (VFILTER.onMap ? ' checked' : '') + '> <span>' + esc(t('vf_onmap')) +
      '</span></label>' +
    '<div class="note">' + esc(t('vf_selected', { n: sel, m: total })) + '</div>' +
    '<div class="btn-row">' +
      '<button class="btn' + (FLEET.layer ? ' primary' : '') + '" id="vf-fleet">' +
        esc(FLEET.layer ? t('vfb_tracks_off') : t('vfb_tracks')) + '</button>' +
      '<button class="btn" id="vf-zoom">' + esc(t('vfb_zoom')) + '</button>' +
    '</div>' +
    (FLEET.capped ? '<div class="note empty">' +
      esc(t('fleet_capped', { n: FLEET.capped, c: FLEET_CAP })) + '</div>' : '') +
    '</div>';
  if (f.sanctioned) {
    h += '<label class="chipbox sanction-chip"><input type="checkbox" id="vf-san"' +
      (VFILTER.sanctioned ? ' checked' : '') + '> ⛔ ' + esc(t('vf_sanctioned')) +
      ' <span class="note">' + f.sanctioned + '</span></label>';
  }
  h += group('fam', t('vf_type'), f.fam, FAMILY_LABEL);
  h += group('size', t('vf_size'), f.size, SIZE_LABEL,
             ['small', 'coastal', 'large', 'very_large']);
  /* Las banderas son muchas; solo las que aparecen de verdad, por volumen. */
  var topFlags = {};
  Object.keys(f.flag).sort(function (a, b) { return f.flag[b] - f.flag[a]; })
    .slice(0, 12).forEach(function (k) { topFlags[k] = f.flag[k]; });
  h += group('flag', t('vf_flag'), topFlags);
  return h ? '<div class="vfacets">' + h +
    '<div class="btn-row"><button class="btn" id="vf-reset">' +
    esc(t('ops_reset')) + '</button></div></div>' : '';
}

function renderVesselTab(filter) {
  var rows = vesselList(filter);
  var h = '<input type="text" id="v-search" placeholder="' +
    esc(t('search_vessel')) + '" value="' + esc(filter || '') + '" autocomplete="off">' +
    facetHtml() +
    '<div class="count">' + t('vessels_found', { n: '<b>' + rows.length + '</b>' }) + '</div>' +
    (window.basinFilterNote ? basinFilterNote('vessels') : '');
  rows.slice(0, 300).forEach(function (r) {
    var bits = [];
    if (r.length_m) { bits.push(r.length_m + ' m'); }
    bits.push(FAMILY_LABEL[r.family] || r.family);
    bits.push(r.flag);
    h += '<div class="card vcard' + (r.sanctioned ? ' sanctioned' : '') +
      '" data-mmsi="' + esc(r.mmsi) + '" tabindex="0" role="button">' +
      '<div class="ttl">' + (r.sanctioned ? '<span class="sban">⛔</span> ' : '') +
        esc(r.name || ('MMSI ' + r.mmsi)) + '</div>' +
      '<div class="meta">' + esc(bits.join(' · ')) + '</div>' +
      '<div class="meta">MMSI ' + esc(r.mmsi) + ' · ' + r.n + ' ' +
        esc(t('positions').toLowerCase()) +
        ' · ' + esc(t('last_fix').toLowerCase()) + ' ' + fmtUTC(r.last) + '</div></div>';
  });
  if (rows.length > 300) { h += '<div class="note">' + t('list_truncated') + '</div>'; }
  var box = document.getElementById('vessels');
  box.innerHTML = h;
  var inp = document.getElementById('v-search');
  inp.addEventListener('input', function () {
    var pos = inp.selectionStart;
    renderVesselTab(inp.value);
    applyVesselFilter();
    var n = document.getElementById('v-search');
    n.focus(); n.setSelectionRange(pos, pos);
  });
  /* Todo cambio de faceta repinta lista Y mapa: el tick es «visible», no
   * «listado». */
  var after = function () { renderVesselTab(filter); applyVesselFilter(); };
  box.querySelectorAll('[data-vf]').forEach(function (cb) {
    cb.addEventListener('change', function () {
      VFILTER[cb.dataset.vf][cb.dataset.k] = cb.checked; after(); });
  });
  var sanCb = document.getElementById('vf-san');
  if (sanCb) { sanCb.addEventListener('change', function () {
    VFILTER.sanctioned = sanCb.checked; after(); }); }
  var onMap = document.getElementById('vf-onmap');
  if (onMap) { onMap.addEventListener('change', function () {
    VFILTER.onMap = onMap.checked; after(); }); }
  var fl = document.getElementById('vf-fleet');
  if (fl) { fl.addEventListener('click', function () {
    if (FLEET.layer) { clearFleetTracks(); } else { showFleetTracks(); }
    after(); }); }
  if (window.bindBasinClear) { bindBasinClear(box); }
  var zm = document.getElementById('vf-zoom');
  if (zm) { zm.addEventListener('click', zoomToSelection); }
  var vfr = document.getElementById('vf-reset');
  if (vfr) { vfr.addEventListener('click', resetVesselFilter); }
  box.querySelectorAll('.vcard').forEach(function (el) {
    /* Entrar desde la lista de buques no es entrar desde una alerta. */
    var go = function () { showVessel(el.dataset.mmsi, undefined, null); };
    el.addEventListener('click', go);
    el.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
  });
}

function rangeBar(mmsi) {
  return '<div class="btn-row">' + RANGES.map(function (r) {
    return '<button class="btn range' + (VESSEL_RANGE === r[1] ? ' primary' : '') +
      '" data-ms="' + (r[1] === null ? '' : r[1]) + '" data-mmsi="' + esc(mmsi) +
      '">' + (r[0] === 'all' ? t('range_all') : r[0]) + '</button>'; }).join('') + '</div>';
}

function coverageBlock(a, b, nPts) {
  var span = b - a;
  var cov = coverageIn(a, b);
  var pct = span > 0 ? (100 * cov / span) : 0;
  var cls = pct < 5 ? 'caution' : '';
  return '<div class="block ' + cls + '"><h4>' + esc(t('what_we_hold')) + '</h4>' +
    '<div class="row"><span class="k">' + esc(t('requested')) + '</span><span>' +
      fmtDur(span) + '</span></div>' +
    '<div class="row"><span class="k">' + esc(t('recorded')) + '</span><span>' +
      fmtDur(cov) + ' (' + pct.toFixed(1) + '%)</span></div>' +
    '<div class="row"><span class="k">' + esc(t('positions')) + '</span><span>' +
      nPts + '</span></div>' +
    '<p class="note">' + esc(t('coverage_gap_note')) + '</p></div>';
}

/* ------------------------------------------------- vessel history view */
/* La alerta desde la que se entro, si se entro desde una. El panel la pinta
 * arriba y con su color: entrar a un buque desde una alerta roja y encontrar
 * una ficha neutra que no menciona la alerta rompe la revision. */
var VESSEL_ALERT = null;

function showVessel(mmsi, rangeMs, ctx) {
  var v = HIST[String(mmsi)];
  if (!v) { return; }
  /* ctx undefined = no se dijo nada, se conserva (los botones de rango
   * reentran aqui). ctx null = se entro sin alerta, se limpia. */
  if (ctx !== undefined) { VESSEL_ALERT = ctx; }
  else if (!SHOWN_VESSEL || SHOWN_VESSEL !== String(mmsi)) { VESSEL_ALERT = null; }
  /* Se guarda la feature entera, no sus propiedades: el boton de volver
   * reabre showDetail(), que espera una feature. */
  var al = VESSEL_ALERT && VESSEL_ALERT.properties;
  var gist = (al && window.alertGist) ? alertGist(al) : null;
  var sev = al && window.severityOf ? severityOf(al) : null;
  /* Entrar a un buque muestra TODO lo que sabemos de el. Antes abria con
   * siete dias y habia que pulsar «All» para ver el resto, asi que la
   * primera impresion era una derrota recortada sin avisar. Los botones de
   * rango siguen ahi para acotar despues. */
  if (rangeMs !== undefined) { VESSEL_RANGE = rangeMs; }
  else if (!SHOWN_VESSEL || SHOWN_VESSEL !== String(mmsi)) { VESSEL_RANGE = null; }
  SHOWN_VESSEL = String(mmsi);
  var tEnd = v.pts[v.pts.length - 1].t;
  var tStart = VESSEL_RANGE === null ? v.pts[0].t : Math.min(v.pts[0].t, tEnd - VESSEL_RANGE);
  if (VESSEL_RANGE !== null) { tStart = tEnd - VESSEL_RANGE; }
  var all = v.pts;
  v = { name: v.name, ship_type: v.ship_type, destination: v.destination,
        pts: all.filter(function (x) { return x.t >= tStart && x.t <= tEnd; }) };
  if (!v.pts.length) { v.pts = [all[all.length - 1]]; }
  /* El rango elegido aqui manda tambien sobre la LINEA TEMPORAL. Sin esto el
   * panel decia «ultimas 24 h» y la barra de abajo seguia mostrando los 15
   * dias enteros: dos controles de tiempo contando cosas distintas. El rango
   * se mide hacia atras desde el ultimo fix DE ESTE BUQUE, no desde ahora,
   * asi que la barra se encuadra en ese mismo tramo. */
  setView(tStart, tEnd);
  TIME.viewMs = VESSEL_RANGE;
  if (TIME.cursor === null || TIME.cursor < tStart || TIME.cursor > tEnd) {
    TIME.cursor = tEnd;
  }
  if (typeof LIVE !== 'undefined' && LIVE.on) { LIVE.follow = false; }
  if (histLayer) { map.removeLayer(histLayer); }
  var ll = v.pts.map(function (x) { return [x.lat, x.lon]; });
  histLayer = L.layerGroup([
    L.polyline(ll, { color: '#ff5cf0', weight: 3, opacity: 1 })
  ]);
  /* Un punto por observacion: donde los puntos se separan, no es que el buque
   * acelerara, es que dejamos de verlo. */
  v.pts.forEach(function (x, i) {
    var lastOne = i === v.pts.length - 1;
    L.circleMarker([x.lat, x.lon], {
      radius: lastOne ? 6 : 3.5,
      color: lastOne ? '#ffd166' : '#ff9cf5', weight: lastOne ? 2 : 1,
      fillColor: lastOne ? '#ffd166' : '#ff5cf0', fillOpacity: 0.9
    }).bindPopup('<div class="note">' + fmtUTC(x.t) + '</div><div class="row">' +
      '<span class="k">SOG</span><span>' +
      (x.sog === null || x.sog === undefined ? '-' : x.sog + ' kn') +
      '</span></div>').addTo(histLayer);
  });
  /* La alerta, sobre la propia derrota. Sin esto el panel dice «desviado 10
   * grados» y la traza no senala donde. Se pinta el tramo de la ventana de
   * la alerta en su color de severidad, encima del rosa. */
  if (gist && sev) {
    var seg = v.pts.filter(function (x) { return x.t >= gist.t0 && x.t <= gist.t1; })
                   .map(function (x) { return [x.lat, x.lon]; });
    if (seg.length > 1) {
      L.polyline(seg, { color: SEVERITY[sev].colour, weight: 7, opacity: 0.85 })
        .addTo(histLayer);
    }
    if (al.lat !== undefined && al.lon !== undefined) {
      L.circleMarker([al.lat, al.lon], {
        radius: 11, color: SEVERITY[sev].ring, weight: 3,
        fillColor: SEVERITY[sev].colour, fillOpacity: 0.55
      }).bindPopup('<div class="k">' + esc(al.indicator) + ' · ' +
        esc(sevLabel(al)) + '</div><div class="note">' + fmtUTC(al.ts_ms) +
        '</div>').addTo(histLayer);
    }
  }
  addRouteMarkers(histLayer, v.pts, mmsi);
  histLayer.addTo(map);
  document.getElementById('map').classList.add('focus-history');
  /* El encuadre tiene que contener la derrota Y el destino declarado. Si el
   * buque va a Kaliningrado, verlo exige alejarse hasta el Baltico entero, y
   * eso es precisamente la informacion: lo lejos que esta de donde dice que
   * va. El encuadre se calcula tras resolver el destino, mas abajo. */
  fitVesselView(mmsi, ll);

  /* Las filas que caen dentro de la ventana de la alerta se marcan. Sin esto
   * se promociona una lista de 253 posiciones y la que importa queda
   * escondida en medio: mover el bloque arriba no sirve de nada si dentro no
   * se senala cual es. */
  var inWin = function (ta, tb) {
    return gist && gist.t0 && tb >= gist.t0 && ta <= gist.t1;
  };
  var rows = '';
  v.pts.slice().reverse().forEach(function (x, i) {
    rows += '<div class="row hrow' + (inWin(x.t, x.t) ? ' in-alert' : '') +
      '" data-lat="' + x.lat + '" data-lon="' + x.lon + '">' +
      '<span class="k">' + fmtUTC(x.t) + '</span><span>' +
      (x.sog === null || x.sog === undefined ? '-' : x.sog + ' kn') + '</span></div>';
    if (i === 0) { return; }
  });

  var gaps = [];
  for (var i = 1; i < v.pts.length; i += 1) {
    var dt = v.pts[i].t - v.pts[i - 1].t;
    if (dt > 15 * 60 * 1000) { gaps.push([v.pts[i - 1].t, v.pts[i].t, dt]); }
  }

  /* Bloques sueltos: el orden depende de por que se abrio el panel, asi que
   * se montan primero y se ensamblan despues. */
  var gapsBlock = gaps.length
    ? '<div class="block caution"><h4>' + esc(t('gaps')) + '</h4><p>' +
        esc(t('gaps_note')) + '</p>' + gaps.map(function (g) {
          return '<div class="row' + (inWin(g[0], g[1]) ? ' in-alert' : '') +
            '"><span class="k">' + fmtUTC(g[0]) + '</span><span>' +
            fmtDur(g[2]) + '</span></div>'; }).join('') + '</div>'
    : '';
  var posBlock = function (open) {
    return '<details' + (open ? ' open' : '') + '><summary>' +
      esc(t('all_positions')) + ' (' + v.pts.length + ')</summary>' +
      '<div class="inner">' + rows + '</div></details>';
  };
  /* El bloque que contiene la prueba de ESTA alerta. Se saca de su sitio y se
   * pone pegado al selector de rango, que es donde mira la vista. */
  var promoted = '';
  if (gist) {
    if (gist.needs === 'gaps' && gapsBlock) { promoted = gapsBlock; gapsBlock = ''; }
    else {
      /* Para los indicadores cuya prueba son las posiciones NO se promociona
       * la lista entera: abrir 1.202 filas para senalar 19 no es poner lo
       * relevante primero, es un muro. Se extraen las de la ventana y la
       * lista completa se queda abajo, plegada, donde siempre estuvo. */
      var win = v.pts.filter(function (x) { return inWin(x.t, x.t); });
      if (win.length) {
        promoted = '<div class="block"><h4>' + esc(t('g_pos_during')) +
          ' (' + win.length + ')</h4>' +
          win.slice().reverse().map(function (x) {
            return '<div class="row hrow in-alert" data-lat="' + x.lat +
              '" data-lon="' + x.lon + '"><span class="k">' + fmtUTC(x.t) +
              '</span><span>' +
              (x.sog === null || x.sog === undefined ? '-' : x.sog + ' kn') +
              '</span></div>'; }).join('') +
          '<p class="note">' + esc(t('g_pos_during_note')) + '</p></div>';
      }
    }
  }

  var gistBlock = gist ? '<div class="block gist sev-' + sev + '">' +
      '<h4>' + esc(t('g_why_h')) + '</h4>' +
      '<div class="gist-head"><span class="badge sev">' + esc(sevLabel(al)) +
        '</span><span class="badge ind">' + esc(al.indicator) + '</span>' +
        '<span class="gist-title">' + esc(gist.title) + '</span></div>' +
      gist.rows.map(function (r) {
        return '<div class="row"><span class="k">' + esc(r[0]) + '</span><span>' +
          esc(r[1]) + '</span></div>'; }).join('') +
      (gist.t0 && gist.t1 && gist.t1 > gist.t0
        ? '<div class="row"><span class="k">' + esc(t('g_window')) + '</span><span>' +
          fmtUTC(gist.t0) + ' → ' + fmtUTC(gist.t1) + '</span></div>' : '') +
      '<p class="note">' + esc(t('g_evidence_below')) + '</p>' +
      '<button class="btn small" id="v-alert">&larr; ' + esc(t('g_back_alert')) +
      '</button></div>' : '';

  var h = '<div class="detail-bar' + (sev ? ' sev-' + sev : '') + '">' +
      '<button class="xbtn big" id="v-back" title="' + esc(t('back')) + '">&times;</button>' +
      '<span class="detail-bar-t">' + esc(v.name || ('MMSI ' + mmsi)) + '</span>' +
    '</div>' +
    '<div class="btn-row">' +
      '<button class="btn primary" id="v-play">&#9654; ' + esc(t('replay')) + '</button>' +
      '<button class="btn" id="v-clear">' + esc(t('hide_history')) + '</button>' +
    '</div>' +
    '<div class="block note-box"><h4>' + esc(t('range_panel')) + '</h4>' +
      rangeBar(mmsi) + '<p class="note">' + esc(t('range_note')) + '</p></div>' +
    gistBlock + promoted +
    '<div class="detail-sub">MMSI ' + esc(mmsi) +
      (v.ship_type ? ' · ' + esc(shipTypeText(v.ship_type) || v.ship_type) : '') +
      (v.destination ? ' · → ' + esc(v.destination) : '') + '</div>' +
    /* El dossier va aqui arriba, no al final: esta es la vista donde se
     * estudia un buque concreto, y «esta sancionado» tiene que verse antes
     * que el historial de posiciones. */
    dossierBlock(mmsi) +
    /* Dos lecturas del mismo buque que no dependen de que el buque coopere:
     * a donde dice que va (y si su rumbo lo respalda) y si el radar lo ve
     * donde el AIS dice. Van antes del recorte porque responden a la
     * pregunta operativa; el recorte es la prueba. */
    '<div id="route-box"></div>' +
    '<div id="confirm-box"></div>' +
    (window.chipHtml
      ? chipHtml(v.pts[v.pts.length - 1].lon, v.pts[v.pts.length - 1].lat,
                 v.pts[v.pts.length - 1].t, 's1', { owner: 'vessel' })
      : '') +
    '<div class="block"><h4>' + esc(t('voyage')) + '</h4>' +
      originDest(mmsi, { destination: v.destination }) + '</div>' +
    '<details><summary>' + esc(t('what_we_hold')) + '</summary><div class="inner">' +
      coverageBlock(tStart, tEnd, v.pts.length) + '</div></details>' +
    '<details><summary>' + esc(t('history')) + '</summary><div class="inner">' +
      '<div class="row"><span class="k">' + esc(t('positions')) + '</span><span>' +
        v.pts.length + '</span></div>' +
      '<div class="row"><span class="k">' + esc(t('first_fix')) + '</span><span>' +
        fmtUTC(v.pts[0].t) + '</span></div>' +
      '<div class="row"><span class="k">' + esc(t('last_fix')) + '</span><span>' +
        fmtUTC(v.pts[v.pts.length - 1].t) + '</span></div>' +
      '<div class="row"><span class="k">' + esc(t('span')) + '</span><span>' +
        fmtDur(v.pts[v.pts.length - 1].t - v.pts[0].t) + '</span></div></div></details>' +
    gapsBlock +
    (promoted ? '' : posBlock(false));

  var box = document.getElementById('detail');
  box.innerHTML = h; box.classList.add('on');
  /* La severidad se declara en el contenedor, no en cada pieza: dentro hay
   * bloques que la necesitan y que no se montan aqui. */
  ['extreme', 'severe', 'moderate', 'minor', 'info'].forEach(function (k) {
    box.classList.remove('sev-' + k);
  });
  if (sev) { box.classList.add('sev-' + sev); }
  if (window.chipBind) {
    box.querySelectorAll('.chip-box').forEach(function (c) { chipBind(c.id); });
  }
  if (window.renderRoute) { renderRoute(mmsi, v); }
  if (window.renderConfirm) { renderConfirm(mmsi, v.pts); }
  document.getElementById('list-view').style.display = 'none';
  showTab('alerts');
  document.getElementById('tab-alerts').scrollTop = 0;
  document.getElementById('v-back').addEventListener('click', function () {
    closeHistory(); hideDetail(); });
  document.getElementById('v-clear').addEventListener('click', function () {
    var b = document.getElementById('v-clear');
    if (histLayer) { closeHistory(); b.textContent = t('show_history'); }
    else { showVessel(mmsi, VESSEL_RANGE); }
  });
  document.getElementById('v-play').addEventListener('click', function () {
    animateTrack(v.pts, 2500); });
  var vAlert = document.getElementById('v-alert');
  if (vAlert) {
    vAlert.addEventListener('click', function () { showDetail(VESSEL_ALERT); });
  }
  if (v.pts.length > 2) { animateTrack(v.pts, 2500); }
  box.querySelectorAll('.range').forEach(function (el) {
    el.addEventListener('click', function () {
      showVessel(el.dataset.mmsi, el.dataset.ms === '' ? null : +el.dataset.ms); });
  });
  box.querySelectorAll('.hrow').forEach(function (el) {
    el.style.cursor = 'pointer';
    el.addEventListener('click', function () {
      map.setView([+el.dataset.lat, +el.dataset.lon], 14); });
  });
}

/* Traza + animacion sin abrir el panel lateral. Lo usa el boton del popup. */
function trackOnly(mmsi) {
  var v = HIST[String(mmsi)];
  if (!v || !v.pts.length) { return; }
  if (histLayer) { map.removeLayer(histLayer); }
  var ll = v.pts.map(function (x) { return [x.lat, x.lon]; });
  histLayer = L.layerGroup([
    L.polyline(ll, { color: '#ff5cf0', weight: 3, opacity: 1 })
  ]);
  v.pts.forEach(function (x, i) {
    var last = i === v.pts.length - 1;
    L.circleMarker([x.lat, x.lon], {
      radius: last ? 6 : 3.5, color: last ? '#ffd166' : '#ff9cf5',
      weight: last ? 2 : 1, fillColor: last ? '#ffd166' : '#ff5cf0',
      fillOpacity: 0.9 }).addTo(histLayer);
  });
  addRouteMarkers(histLayer, v.pts, mmsi);
  addRouteMarkers(histLayer, v.pts, mmsi);
  histLayer.addTo(map);
  document.getElementById('map').classList.add('focus-history');
  if (v.pts.length > 2) { animateTrack(v.pts, 4000, true); }
}

/* Inicio, fin y cada alerta del buque, con su fecha y hora sobre el mapa.
 * Una traza sin marcas temporales no se puede leer: no se sabe por donde
 * empezo ni cuando paso por el punto que importa. */
function addRouteMarkers(group, pts, mmsi) {
  /* Dos sucesos en el mismo punto imprimian sus etiquetas una sobre otra y
   * no se leia ninguna. Se escalonan en vertical segun cuantas haya ya cerca:
   * mejor una columna legible que un amasijo. */
  var placed = [];
  var tag = function (ll, cls, title, when) {
    var near = placed.filter(function (p) {
      return Math.abs(p[0] - ll[0]) < 0.0025 && Math.abs(p[1] - ll[1]) < 0.0060;
    }).length;
    placed.push(ll);
    L.marker(ll, { icon: L.divIcon({ className: 'rtag ' + cls,
      html: '<b>' + esc(title) + '</b><span>' + esc(when) + '</span>',
      iconSize: null, iconAnchor: [0, 34 + near * 30] }), interactive: false }).addTo(group);
  };
  var a = pts[0], b = pts[pts.length - 1];
  L.circleMarker([a.lat, a.lon], { radius: 7, color: '#ffffff', weight: 2,
    fillColor: '#2fbf71', fillOpacity: 1 }).addTo(group);
  tag([a.lat, a.lon], 'start', t('route_start'), fmtUTC(a.t));
  L.circleMarker([b.lat, b.lon], { radius: 7, color: '#ffffff', weight: 2,
    fillColor: '#ffd166', fillOpacity: 1 }).addTo(group);
  tag([b.lat, b.lon], 'end', t('route_end'), fmtUTC(b.t));

  (window.alertFeatures || []).forEach(function (f) {
    var p = f.properties;
    if (String(p.mmsi) !== String(mmsi) || p.kind !== 'alert') { return; }
    if (p.ts_ms < a.t || p.ts_ms > b.t) { return; }
    var ll = [f.geometry.coordinates[1], f.geometry.coordinates[0]];
    L.circleMarker(ll, { radius: 9, color: sevRing(p), weight: 3,
      fillColor: sevColour(p), fillOpacity: 0.75 })
      .bindPopup('<h4>' + esc(p.indicator) + ' · ' + esc(sevLabel(p)) + '</h4>' +
        '<div class="note">' + fmtUTC(p.ts_ms) + '</div>').addTo(group);
    tag(ll, 'alert', p.indicator, fmtUTC(p.ts_ms).slice(11));
  });
}

function closeHistory() {
  if (histLayer) { map.removeLayer(histLayer); histLayer = null; }
  if (window.clearRoute) { clearRoute(); }
  if (window.confirmClear) { confirmClear(); }
  stopAnim();
  /* Devolver la linea temporal al intervalo completo: el encuadre estrecho
   * pertenecia al buque que se acaba de cerrar. */
  TIME.viewMs = null;
  applyView();
  renderTimeBar();
  document.getElementById('map').classList.remove('focus-history');
}

/* ------------------------------------------------- the time bar */
function renderTimeBar() {
  var el = document.getElementById('timebar');
  var liveGap = TIME.now - TIME.t1;
  var live = (typeof LIVE !== 'undefined' && LIVE.on) || liveGap < 5 * 60 * 1000;
  var cur = TIME.cursor === null ? TIME.t1 : TIME.cursor;
  var w = inWindow(cur);
  var snap = drawSnapshot(cur);

  el.innerHTML =
    '<div class="panel-head"><b>' + esc(t('tb_time')) + '</b>' +
      '<button class="xbtn" data-close="timebar" title="hide">&times;</button></div>' +
    '<div class="tb-head">' +
      '<span class="tb-time">' + fmtUTC(cur) + '</span>' +
      '<span class="note">' + (w ? t('in_window') : t('between_windows')) + '</span>' +
    '</div>' +
    (LIVE && LIVE.on ? '<div class="tb-live-row">' +
      '<span class="note">' + (LIVE.err
        ? '<span class="empty">' + esc(t('live_err', { e: LIVE.err })) + '</span>'
        : t('live_last', { a: LIVE.newest ? fmtDur(TIME.now - LIVE.newest) : '-',
                           n: LIVE.n })) + '</span>' +
      /* Aqui habia un boton «Back to now» que ejecutaba linea por linea lo
       * mismo que «Latest», tres botones mas abajo. Dos controles para la
       * misma accion solo obligan a elegir. En su lugar se dice POR QUE el
       * cursor no esta en el presente, que es lo que no se sabia. */
      (LIVE.follow ? '' : '<span class="note tb-parked">' +
        esc(t('tb_parked')) + '</span>') +
      '</div>' : '') +
    '<input type="range" id="tb-range" min="' + TIME.v0 + '" max="' + TIME.v1 +
      '" step="60000" value="' + Math.max(TIME.v0, Math.min(TIME.v1, cur)) + '">' +
    /* Los extremos del DESLIZADOR, no dos fechas sueltas. Sin etiqueta se
     * leian como un dato mas; con ella se entiende que son hasta donde llega
     * el control que tienes encima. */
    '<div class="tb-foot">' +
      '<span class="note">' + esc(t('tb_from')) + ' ' + fmtUTC(TIME.v0) + '</span>' +
      '<span class="note tb-shown" title="' + esc(t('tb_shown_help')) + '">' +
        shownText(snap) + '</span>' +
      '<span class="note">' + esc(t('tb_to')) + ' ' + fmtUTC(TIME.v1) + '</span>' +
    '</div>' +
    '<div class="btn-row">' +
      '<button class="btn ' + (LIVE && LIVE.on ? 'primary' : '') + '" id="tb-live">' +
        (LIVE && LIVE.on ? '● ' + t('live_on') : t('go_live')) + '</button>' +
      '<input type="date" id="tb-date" value="' +
        new Date(cur).toISOString().slice(0, 10) + '" min="' +
        new Date(TIME.t0).toISOString().slice(0, 10) + '" max="' +
        new Date(TIME.t1).toISOString().slice(0, 10) + '">' +
      '<select id="tb-view">' + [['1h', 3600e3], ['24h', 24 * 3600e3],
        ['7d', 7 * 86400e3], ['all', null]].map(function (r) {
          return '<option value="' + (r[1] === null ? '' : r[1]) + '"' +
            (TIME.viewMs === r[1] ? ' selected' : '') + '>' +
            (r[0] === 'all' ? t('range_all') : r[0]) + '</option>'; }).join('') +
      '</select>' +
      '<button class="btn" id="tb-prev" title="' + esc(t('tb_prev_h')) + '">&larr; ' +
        esc(t('tb_prev')) + '</button>' +
      '<button class="btn" id="tb-play" title="' + esc(t('tb_play_h')) + '">' +
        (TIME.playing ? '❚❚ ' + esc(t('tb_pause')) : '▶ ' + esc(t('tb_play'))) +
        '</button>' +
      '<button class="btn" id="tb-next" title="' + esc(t('tb_next_h')) + '">' +
        esc(t('tb_next')) + ' &rarr;</button>' +
      '<button class="btn primary" id="tb-latest">' + t('latest') + '</button>' +
    '</div>' +
    '<div class="tb-lanes">' +
      lanesHtml() + '</div>' +
    overlapNote() +
    '<div class="note">' + esc(t('lane_hint')) + '</div>' +
    /* AQUI IBA EL AVISO DE «hay que compilar otra vez».
     *
     * Ya no hace falta, y mantenerlo seria mentir al reves: el motor del
     * servidor evalua los indicadores y construye las trazas sobre una
     * ventana que llega hasta el borde de lo compilado, y el visor las
     * fusiona en el mismo HIST. Lo grabado despues del build SI se ve.
     *
     * Solo queda un caso en que el tramo reciente no esta cubierto: que no
     * haya motor --- sirviendo con `python -m http.server`, por ejemplo--- o
     * que el hueco del build supere el tope de la ventana. Entonces se dice
     * eso, que es otra cosa. */
    staleNote() +
    '<div class="note">' + t('coverage_note', {
        n: TIME.win.length, c: fmtDur(TIME.win.reduce(function (a, x) {
          return a + (x[1] - x[0]); }, 0)),
        s: fmtDur(TIME.t1 - TIME.t0) }) + '</div>';

  if (window.bindCloses) { bindCloses(); }
  if (window.lanesBind) { lanesBind(el); }
  /* La linea de tiempo es el mando: pulsar una pasada Sentinel lleva el cursor
   * a su instante exacto de adquisicion y TODO se sincroniza con el. Pulsar en
   * el carril lleva al instante correspondiente a esa posicion. */
  el.querySelectorAll('.lane-b').forEach(function (lb) {
    lb.addEventListener('click', function (ev) {
      stopPlay();
      var mark = ev.target.closest ? ev.target.closest('i[data-t]') : null;
      if (mark) { setCursor(+mark.dataset.t); return; }
      var r = lb.getBoundingClientRect();
      var f = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
      setCursor(TIME.v0 + f * (TIME.v1 - TIME.v0));
    });
  });
  var rng = document.getElementById('tb-range');
  rng.addEventListener('input', function () { setCursor(+rng.value, true); });
  document.getElementById('tb-latest').addEventListener('click', function () {
    stopPlay();
    if (window.stopAnim) { stopAnim(); }
    if (typeof LIVE !== 'undefined' && LIVE.on) { LIVE.follow = true; }
    setCursor(TIME.t1, false, true); });
  document.getElementById('tb-prev').addEventListener('click', function () { stepWindow(-1); });
  document.getElementById('tb-next').addEventListener('click', function () { stepWindow(1); });
  document.getElementById('tb-play').addEventListener('click', togglePlay);
  document.getElementById('tb-live').addEventListener('click', function () {
    if (LIVE.on) { liveOff(); } else { liveOn(); } });
  document.getElementById('tb-date').addEventListener('change', function (e) {
    var d = new Date(e.target.value + 'T00:00:00Z').getTime();
    if (!isNaN(d)) { setView(d, d + 86400e3); setCursor(d + 86399e3); } });
  document.getElementById('tb-view').addEventListener('change', function (e) {
    TIME.viewMs = e.target.value === '' ? null : +e.target.value;
    applyView(); renderTimeBar(); });
  /* «Latest» es el unico camino de vuelta al presente: reengancha el vivo,
   * para la reproduccion y lleva el cursor al fix mas nuevo. */
}

/* CUANTAS FUENTES COINCIDEN EN EL CURSOR.
 *
 * Es la respuesta directa a «cuando puedo superponer dos o mas mapas». Las
 * pistas lo ENSEÑAN; esta linea lo CUENTA, que es lo que se mira primero. Si
 * el numero es uno, no hay nada que superponer en ese instante y mas vale
 * saberlo antes de encender cuatro capas y no entender por que tres salen
 * vacias. */
function overlapNote() {
  if (!window.lanesAt) { return ''; }
  var cur = TIME.cursor === null ? TIME.v1 : TIME.cursor;
  var r = lanesAt(cur);
  if (!r.total) { return ''; }
  return '<div class="note ov-note' + (r.hit.length > 1 ? ' ov-ok' : '') + '">' +
    esc(t('lane_overlap', { n: r.hit.length, m: r.total })) +
    (r.hit.length ? ' <span class="ov-l">' + esc(r.hit.join(' · ')) + '</span>' : '') +
    '</div>';
}

/* Lo que queda del aviso de build. Ahora solo se dice cuando es verdad: sin
 * motor en vivo, o con un hueco mayor que la ventana que el motor cubre. */
function staleNote() {
  if (!window.buildAgeH || buildAgeH() <= BUILD_STALE_H) { return ''; }
  /* Cubierto = la VENTANA DEL MOTOR llega al borde de lo compilado. Se
   * pregunta por la ventana, no por el fix mas antiguo recibido: si la
   * grabadora estuvo parada no hay fixes en ese tramo y tampoco los habria
   * tras compilar, asi que no es un hueco que un build arregle. */
  var covered = window.LIVEV && LIVEV.winStart &&
    (!TIME.builtTo || LIVEV.winStart <= TIME.builtTo + 3600e3);
  if (covered) {
    return '<div class="note live-note">' + esc(t('lane_live_cover', {
      h: ((LIVEV.newest - LIVEV.winStart) / 3600e3).toFixed(1),
      d: fmtUTC(LIVEV.newest), n: LIVEV.vessels })) + '</div>';
  }
  return '<div class="note stale-note">' + esc(t(
    window.LIVEV && LIVEV.winStart ? 'lane_live_gap' : 'lane_nolive',
    { h: Math.round(buildAgeH()), d: fmtUTC(TIME.builtTo),
      g: window.LIVEV && LIVEV.winStart ? fmtUTC(LIVEV.winStart) : '-' })) + '</div>';
}

function applyView() {
  if (TIME.viewMs === null) { TIME.v0 = TIME.t0; TIME.v1 = TIME.t1; return; }
  TIME.v1 = TIME.t1;
  TIME.v0 = Math.max(TIME.t0, TIME.t1 - TIME.viewMs);
}
function setView(a, b) {
  TIME.v0 = Math.max(TIME.t0, a); TIME.v1 = Math.min(TIME.t1, b);
  if (TIME.v1 <= TIME.v0) { TIME.v1 = TIME.v0 + 3600e3; }
}

var _imgDebounce = null;
var _alertDebounce = null;
/* Las pistas viven en lanes.js: una por fuente, agrupadas y plegables. Aqui
 * habia una segunda version que solo sabia de AIS y los dos Sentinel, y
 * mantener dos constructores de la misma pista es como se consigue que una
 * ensene algo distinto de la otra. */

/* Lo que dice el contador del centro de la barra. Con la instantanea apagada
 * NO son «0 de 0»: es que esa vista no depende del cursor, y decir cero hacia
 * pensar que no hay buques cuando la pantalla esta llena de ellos. */
function shownText(snap) {
  if (snap && snap.off) { return t('shown_not_timed'); }
  return t('shown_vessels', { f: '<b>' + snap.fresh + '</b>', n: snap.total });
}

function setCursor(at, light, fromLive) {
  TIME.cursor = Math.max(TIME.t0, Math.min(TIME.t1, at));
  /* Mover el cursor a mano estando en vivo no apaga el modo: lo DESENGANCHA.
   * Se sigue sondeando cada 60 s (asi la linea temporal sigue creciendo),
   * pero el cursor se queda donde lo dejaste. «Latest» lo reengancha. */
  if (!fromLive && typeof LIVE !== 'undefined' && LIVE.on) { LIVE.follow = false; }
  /* La imagen sigue al cursor, con freno: arrastrar el deslizador no puede
   * disparar una busqueda STAC por cada pixel. */
  if (window.imageryFollowCursor) {
    if (_imgDebounce) { clearTimeout(_imgDebounce); }
    _imgDebounce = setTimeout(imageryFollowCursor, 450);
  }
  /* Las capas de Copernicus Marine tambien siguen al cursor: mirar la
   * corriente del instante en que paso algo es la mitad de su valor. */
  if (window.marineFollowCursor) { marineFollowCursor(); }
  if (window.emodFollowCursor) { emodFollowCursor(); }
  if (window.refreshAlertViews) {
    if (_alertDebounce) { clearTimeout(_alertDebounce); }
    _alertDebounce = setTimeout(refreshAlertViews, 180);
  }
  if (light) {
    var w = inWindow(TIME.cursor);
    var snap = drawSnapshot(TIME.cursor);
    var head = document.querySelector('#timebar .tb-time');
    if (head) { head.textContent = fmtUTC(TIME.cursor); }
    var st = document.querySelector('#timebar .tb-head .note');
    if (st) { st.textContent = w ? t('in_window') : t('between_windows'); }
    var f = document.querySelectorAll('#timebar .tb-foot .note')[1];
    if (f) { f.innerHTML = shownText(snap); }
    document.querySelectorAll('#timebar .lane-cur').forEach(function (c) {
      c.style.left = (100 * (TIME.cursor - TIME.v0) /
                      Math.max(1, TIME.v1 - TIME.v0)) + '%'; });
  } else { renderTimeBar(); }
}

/* Saltar de ventana de cobertura en ventana: fuera de ellas no hay dato nuevo,
 * asi que deslizar por el hueco solo envejece los marcadores. */
function stepWindow(dir) {
  stopPlay();
  var cur = TIME.cursor === null ? TIME.t1 : TIME.cursor;
  var best = null;
  TIME.win.forEach(function (x) {
    if (dir > 0 && x[0] > cur && (best === null || x[0] < best)) { best = x[0]; }
    if (dir < 0 && x[1] < cur && (best === null || x[1] > best)) { best = x[1]; }
  });
  if (best !== null) { setCursor(best); }
}

function togglePlay() {
  if (TIME.playing) { stopPlay(); return; }
  /* Un solo reloj en marcha. La reproduccion de un buque tambien mueve el
   * cursor, asi que dejar las dos corriendo seria pelearse por el. */
  if (window.stopAnim) { stopAnim(); }
  TIME.playing = true;
  var w = inWindow(TIME.cursor === null ? TIME.t1 : TIME.cursor) ||
          TIME.win[TIME.win.length - 1];
  if (w) { TIME.cursor = w[0]; }
  renderTimeBar();
  TIME.timer = setInterval(function () {
    var win = inWindow(TIME.cursor);
    var end = win ? win[1] : TIME.t1;
    setCursor(TIME.cursor + 60000, true);
    if (TIME.cursor >= end) { stopPlay(); renderTimeBar(); }
  }, 250);
}
function stopPlay() {
  TIME.playing = false;
  if (TIME.timer) { clearInterval(TIME.timer); TIME.timer = null; }
}

/* La cobertura, del ALMACEN y no del build.
 *
 * La pista venia del manifest, asi que se congelaba en el instante de
 * compilar: a las 42 h parecia que faltaban datos recientes. El servidor
 * recalcula las ventanas del polllog a peticion (31 kB/dia), asi que la
 * pista puede estar al dia sin recompilar nada.
 *
 * Lo que NO se puede adelantar asi son los buques y las alertas: esos salen
 * del pipeline de indicadores, que si es trabajo de build. Por eso las
 * ventanas posteriores al build se dibujan huecas en vez de llenas.
 */
function loadLiveCoverage() {
  return fetch('/coverage').then(function (r) {
    if (!r.ok) { throw new Error('HTTP ' + r.status); }
    return r.json();
  }).then(function (d) {
    var w = d.windows_ms || [];
    if (!w.length) { return; }
    TIME.win = w;
    if (d.newest_ms && d.newest_ms > TIME.t1) { TIME.t1 = d.newest_ms; }
    TIME.coverageLive = true;
    applyView();
    renderTimeBar();
  }).catch(function () { /* sin servidor propio: se queda la del build */ });
}

function initTime(manifest, tracksFc) {
  var tm = manifest.time || {};
  TIME.win = tm.coverage_windows_ms || [];
  /* Hasta donde llega lo COMPILADO. Separado de t1, que ahora puede ir mas
   * alla gracias a la cobertura viva. */
  TIME.builtTo = tm.dataset_end_ms || 0;
  TIME.t0 = tm.dataset_start_ms || 0;
  TIME.t1 = tm.dataset_end_ms || 0;
  TIME.built = tm.built_epoch_ms || 0;
  TIME.now = Date.now();
  buildHistory(tracksFc);
  applyView();
  if (window.loadPassCatalogue) {
    /* manifest.aoi YA es [minlon, minlat, maxlon, maxlat], que es el orden
     * que pide STAC. La version anterior permutaba a [lat, lon, lat, lon] y
     * acababa pidiendo escenas de lon 59-61, lat 22-30: el mar de Arabia.
     * Los carriles Sentinel de la linea de tiempo llevaban meses mostrando
     * pasadas del sitio equivocado, y por eso el recorte no encontraba
     * ninguna que cubriera el golfo. */
    loadPassCatalogue(TIME.t0, TIME.t1, manifest.aoi);
  }
  renderVesselTab('');
  renderTimeBar();
  /* La cobertura del almacen, que puede ir por delante del build. Se refresca
   * cada cinco minutos: la grabadora escribe cada 60 s y la pista no necesita
   * mas precision que eso. */
  loadLiveCoverage();
  setInterval(loadLiveCoverage, 300000);
  /* El eje temporal de cada fuente externa. Se pide una vez y se refresca
   * cada diez minutos: una ventana de pronostico avanza con el reloj. */
  if (window.lanesLoad) { lanesLoad(); setInterval(lanesLoad, 600000); }
  setInterval(function () { TIME.now = Date.now(); }, 30000);
}

var SHOWN_VESSEL = null;

/* Encuadre de la vista de buque: derrota completa mas el puerto declarado si
 * se conoce. maxZoom evita que un buque parado llene la pantalla con 200 m
 * de mar. */
function fitVesselView(mmsi, latlngs) {
  var pts = latlngs.slice();
  var v = HIST[String(mmsi)] || {};
  var raw = v.destination || (vinfo(mmsi) || {}).destination;
  var r = window.resolveDestination ? resolveDestination(raw) : null;
  if (r && r.port) { pts.push([r.port.lat, r.port.lon]); }
  if (!pts.length) { return; }
  map.fitBounds(L.latLngBounds(pts), { padding: [60, 60], maxZoom: 13 });
}

/* ------------------------------------------- proyeccion de ruta declarada */
/* El AIS lleva un campo `destination` que teclea la tripulacion. No es un
 * identificador y a veces no es ni un puerto, pero cuando lo es permite algo
 * que ningun otro dato da: comparar DONDE DICE QUE VA con HACIA DONDE VA.
 *
 * Esa diferencia es el indicador. Un buque cuyo rumbo sobre el fondo no
 * apunta a su destino declarado esta haciendo otra cosa: desviandose,
 * esperando, maniobrando, o mintiendo en el campo. El visor no decide cual;
 * mide el angulo y lo pone encima de la mesa. */
var ROUTE = { layer: null };

function clearRoute() {
  if (ROUTE.layer) { map.removeLayer(ROUTE.layer); ROUTE.layer = null; }
  delete layers.route;
}

function renderRoute(mmsi, v) {
  clearRoute();
  var el = document.getElementById('route-box'); if (!el) { return; }
  var vi = vinfo(mmsi) || {};
  var raw = v.destination || vi.destination || (HIST[String(mmsi)] || {}).destination;
  var r = window.resolveDestination ? resolveDestination(raw) : null;
  var last = v.pts[v.pts.length - 1];

  if (!r || !raw) {
    el.innerHTML = '<div class="block"><h4>' + esc(t('route_h')) + '</h4>' +
      '<p class="note">' + esc(t('route_none')) + '</p></div>';
    return;
  }
  if (!r.port) {
    el.innerHTML = '<div class="block"><h4>' + esc(t('route_h')) + '</h4>' +
      '<div class="row"><span class="k">' + esc(t('route_declared')) +
        '</span><span class="mono">' + esc(r.text) + '</span></div>' +
      '<p class="note">' + esc(t(r.via === 'not-a-destination'
        ? 'route_not_dest' : 'route_unresolved')) + '</p></div>';
    return;
  }

  var brg = bearingTo(last.lon, last.lat, r.port.lon, r.port.lat);
  var distNm = haversineM(last.lon, last.lat, r.port.lon, r.port.lat) / 1852;
  /* COG del ultimo tramo real, no el campo COG: el campo puede venir viejo. */
  var cog = null;
  if (v.pts.length >= 2) {
    var a = v.pts[v.pts.length - 2];
    if (haversineM(a.lon, a.lat, last.lon, last.lat) > 50) {
      cog = bearingTo(a.lon, a.lat, last.lon, last.lat);
    }
  }
  var gap = cog === null ? null : angleGap(cog, brg);
  var sog = last.sog;
  var etaH = (sog && sog > 0.5) ? distNm / sog : null;

  ROUTE.layer = L.layerGroup();
  /* Discontinua y en verde azulado: es una PROYECCION, no una derrota. Que no
   * se confunda con la traza magenta de lo que el buque hizo de verdad. */
  L.polyline([[last.lat, last.lon], [r.port.lat, r.port.lon]],
    { color: '#2dd4bf', weight: 2, opacity: 0.85, dashArray: '8 6' })
    .bindPopup('<h4>' + esc(t('route_h')) + '</h4>' +
      table({ declared: r.text, port: r.port.name, locode: r.port.locode,
              bearing_deg: Math.round(brg), distance_nm: Math.round(distNm),
              resolved_via: r.via }) +
      '<p class="note">' + esc(t('route_note')) + '</p>').addTo(ROUTE.layer);
  L.circleMarker([r.port.lat, r.port.lon], { radius: 8, color: '#2dd4bf',
    weight: 3, fillColor: '#06101a', fillOpacity: 1 })
    .bindPopup('<h4>' + esc(r.port.name) + '</h4><div class="note">' +
      esc(r.port.locode) + ' · ' + esc(t('route_declared')) + '</div>')
    .addTo(ROUTE.layer);
  L.marker([r.port.lat, r.port.lon], { interactive: false, icon: L.divIcon({
    className: 'rtag dest', iconSize: null, iconAnchor: [0, 34],
    html: '<b>' + esc(t('route_dest')) + '</b><span>' + esc(r.port.name) + '</span>' }) })
    .addTo(ROUTE.layer);
  ROUTE.layer.addTo(map);
  layers.route = ROUTE.layer;

  var off = gap !== null && gap > 35;
  el.innerHTML = '<div class="block' + (off ? ' caution' : '') + '"><h4>' +
    esc(t('route_h')) + '</h4>' +
    '<div class="row"><span class="k">' + esc(t('route_declared')) +
      '</span><span>' + esc(r.port.name) + ' <span class="note mono">' +
      esc(r.text) + '</span></span></div>' +
    '<div class="row"><span class="k">' + esc(t('route_bearing')) +
      '</span><span>' + Math.round(brg) + '° · ' + Math.round(distNm) + ' NM</span></div>' +
    (cog !== null ? '<div class="row"><span class="k">' + esc(t('route_making')) +
      '</span><span>' + Math.round(cog) + '°</span></div>' : '') +
    (gap !== null ? '<div class="row"><span class="k">' + esc(t('route_gap')) +
      '</span><span class="' + (off ? 'empty' : 'ok') + '">' + Math.round(gap) +
      '°</span></div>' : '') +
    (etaH !== null ? '<div class="row"><span class="k">' + esc(t('route_eta')) +
      '</span><span>' + fmtDur(etaH * 3600e3) + ' @ ' + sog + ' kn</span></div>' : '') +
    '<p class="note">' + esc(t(off ? 'route_off' : 'route_note')) + '</p>' +
    (r.via !== 'exact' ? '<p class="note empty">' +
      esc(t('route_fuzzy', { v: r.via })) + '</p>' : '') + '</div>';
}

/* ------------------------------------- confirmacion SAR sobre el historial */
function renderConfirm(mmsi, pts) {
  var el = document.getElementById('confirm-box'); if (!el) { return; }
  var paint = function (st) {
    var done = st.rows.length, tot = st.total || 0;
    var hits = st.rows.filter(function (r) { return r.hit; });
    var h = '<div class="block"><h4>' + esc(t('cf_h')) + '</h4>';
    if (st.rows.length === 1 && st.rows[0].error) {
      h += '<p class="note empty">' + esc(st.rows[0].error) + '</p></div>';
      el.innerHTML = h; return;
    }
    if (st.busy) {
      h += '<p class="note">' + esc(t('cf_running', { n: done, m: tot })) + '</p>';
    } else if (!tot) {
      /* Sin pasada no hay nada que contrastar y el bloque sobra: una linea.
       * Y si no hay pasada sobre la derrota, el recorte de al lado tampoco
       * tiene nada util que enseñar: se pliegan juntos, que es lo que pedia
       * el usuario al decir «que se oculte todo de una sola vez». */
      el.innerHTML = '<div class="block quiet"><span class="note">' +
        esc(t('cf_h')) + ' · ' + esc(t('cf_nopass_short')) + '</span></div>';
      if (window.chipCollapseOwned) {
        chipCollapseOwned('vessel', t('cf_nopass_short'));
      }
      return;
    } else {
      h += '<div class="row"><span class="k">' + esc(t('cf_passes')) +
        '</span><span>' + tot + '</span></div>' +
        '<div class="row"><span class="k">' + esc(t('cf_confirmed')) +
        '</span><span class="' + (hits.length ? 'ok' : 'empty') + '">' +
        hits.length + '</span></div>';
    }
    st.rows.forEach(function (r) {
      h += '<div class="row"><span class="k">' + fmtUTC(r.t).slice(5, 16) +
        '</span><span class="' + (r.hit ? 'ok' : 'empty') + '">' +
        (r.error ? esc(t('cf_err'))
          : r.hit ? '✓ ' + Math.round(r.hit.distance_m) + ' m · ~' +
                    r.hit.length_m + ' m'
                  : '— ' + esc(t('cf_nothing'))) + '</span></div>';
    });
    if (!st.busy && tot) {
      h += '<p class="note">' + esc(t(hits.length ? 'cf_h_note' : 'cf_none_note')) + '</p>';
    }
    h += '</div>';
    el.innerHTML = h;
  };
  /* Arranca solo: el usuario ya dijo lo que queria al abrir el buque, y
   * obligarle a pulsar otro boton para la mitad del valor no tiene sentido.
   * Las pasadas van en serie y los recortes estan cacheados, asi que repetir
   * un buque es casi instantaneo. */
  el.innerHTML = '<div class="block"><h4>' + esc(t('cf_h')) + '</h4>' +
    '<p class="note">' + esc(t('cf_intro')) + '</p></div>';
  if (window.confirmTrack) { confirmTrack(mmsi, pts, paint); }
}
