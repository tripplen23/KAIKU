/* marine.js - Copernicus Marine sobre el mapa.
 *
 * Veinte capas en cinco grupos: corriente, oleaje, hielo, agua y reanalisis.
 * Todas por WMTS, que Copernicus sirve SIN credenciales --verificado-- y que
 * pasa por el proxy, asi que la segunda vista de una tesela es gratis.
 *
 * SIGUEN AL CURSOR TEMPORAL. Esa es la mitad del valor: mirar la corriente
 * del instante en que un buque hizo algo raro, no la de ahora. El WMTS acepta
 * `time=`, asi que basta con reconstruir la URL al mover el cursor. Se frena
 * a un cambio por hora: pedir teselas nuevas por cada pixel del deslizador
 * seria absurdo, y los modelos tienen paso horario o diario de todos modos.
 *
 * EL LIMITE VA EN LA CAPA, NO EN UNA NOTA AL PIE. La direccion de corriente
 * superficial de CMEMS tiene 87 grados de error RMS, validado contra siete
 * fondeos. Sirve para decir «habia corriente», no para calcular una deriva.
 * Quien encienda la capa lo lee ahi mismo.
 */
'use strict';

var MARINE = { cat: null, on: {}, at: {} };

function loadMarine(cat) {
  MARINE.cat = cat;
  if (window.renderLayerPanel) { renderLayerPanel(); }
  return cat;
}

function marineById(id) {
  var L = (MARINE.cat && MARINE.cat.layers) || [];
  for (var i = 0; i < L.length; i += 1) { if (L[i].id === id) { return L[i]; } }
  return null;
}

/* El instante que se pide a CADA capa, redondeado a SU cadencia.
 *
 * Antes se redondeaba a la hora para todas. Era un supuesto, y era falso: la
 * corriente y el nivel del mar se publican cada 15 minutos. Redondear a la
 * hora tiraba tres cuartas partes de la resolucion que ya estabamos pagando,
 * y en un estrecho con marea 45 minutos no son un detalle.
 *
 * La cadencia no se adivina: la DECLARA el servicio en la dimension `time` de
 * sus capacidades, y el build la trae en `step_s` (custody/marine.py).
 */
function marineStep(def) { return (def && def.step_s) || 3600; }

function marineCursor() {
  return (typeof TIME !== 'undefined' && TIME.cursor !== null)
    ? TIME.cursor : Date.now();
}

/* Dentro de lo que la capa declara tener. Fuera de su ventana el servicio
 * devuelve una tesela vacia, que sobre el mapa se lee como «aqui no hay
 * corriente» en vez de «no hay dato». */
function marineHas(def, at) {
  var w = def && def.time;
  if (!w || !w.start_ms || !w.end_ms) { return true; }
  return at >= w.start_ms && at <= w.end_ms;
}

function marineTimeFor(def, at) {
  var st = marineStep(def) * 1000;
  var t = at === undefined ? marineCursor() : at;
  var w = (def && def.time) || {};
  if (w.start_ms && t < w.start_ms) { t = w.start_ms; }
  if (w.end_ms && t > w.end_ms) { t = w.end_ms; }
  return new Date(Math.floor(t / st) * st).toISOString()
    .replace(/\.\d+Z$/, '.000Z');
}

/* Compatibilidad: lo que se escribe en el panel cuando no hay una capa
 * concreta de la que hablar. Paso horario, que es la cadencia mas comun. */
function marineTime() { return marineTimeFor(null); }

function marineUrl(def) {
  var u = def.template + '&time=' + marineTimeFor(def);
  return (window.PROXY && PROXY.on)
    ? '/cache/tile/{z}/{x}/{y}?tpl=' + encodeURIComponent(u) : u;
}

function marineOn(id, on) {
  var def = marineById(id);
  if (!def) { return; }
  if (!on) {
    if (MARINE.on[id]) { map.removeLayer(MARINE.on[id]); delete MARINE.on[id]; }
    delete layers[id];
    if (window.renderLayerPanel) { renderLayerPanel(); }
    return;
  }
  if (MARINE.on[id]) { return; }
  var lyr = L.tileLayer(marineUrl(def), {
    opacity: 0.75, maxZoom: 12, zIndex: 20, crossOrigin: true,
    attribution: MARINE.cat.attribution
  });
  lyr.addTo(map);
  MARINE.on[id] = lyr;
  layers[id] = lyr;
  if (window.renderLayerPanel) { renderLayerPanel(); }
}

/* Al mover el cursor, repintar lo encendido con el nuevo instante. */
function marineFollowCursor() {
  /* Por capa: con cadencias de 15 min y de 1 h mezcladas, una clave global
   * obligaria a repintar la horaria cuatro veces por hora sin que cambie un
   * solo pixel, o a no repintar la de 15 min cuando si cambia. */
  var any = false;
  Object.keys(MARINE.on).forEach(function (id) {
    var def = marineById(id);
    if (!def) { return; }
    var k = marineTimeFor(def);
    if (MARINE.at[id] === k) { return; }
    MARINE.at[id] = k;
    MARINE.on[id].setUrl(marineUrl(def));
    any = true;
  });
  if (any && window.renderLayerPanel) { renderLayerPanel(); }
}

/* La escala de color, tal cual la sirve Copernicus.
 *
 * Se pide al servicio en vez de redibujarla: el SVG que devuelve es el de la
 * MISMA paleta con la que pinta las teselas, asi que no pueden discrepar. Una
 * escala que no corresponde al mosaico es peor que ninguna.
 *
 * Solo acepta `image/svg+xml`; con `image/png` responde 400. Y la URL que
 * anuncia en sus capacidades viene con el FORMAT doblemente escapado, que
 * tambien da 400 -- se normaliza en el build (custody/marine.py).
 */
function marineLegend(l) {
  var u = (window.PROXY && PROXY.on)
    ? '/cache/img?u=' + encodeURIComponent(l.legend) : l.legend;
  return '<div class="cm-legend">' +
    '<img src="' + esc(u) + '" alt="' + esc(t('cm_scale', { n: l.name })) + '" ' +
    'loading="lazy">' +
    '<div class="cm-legend-t"><div class="k">' + esc(l.title || l.name) + '</div>' +
    '<p class="note">' + esc(t('cm_scale_note')) + '</p>' +
    (l.style.indexOf('Vector') >= 0
      ? '<p class="note">' + esc(t('cm_vector')) + '</p>' : '') +
    '</div></div>';
}

/* UNA FILA, una capa. Extraida del panel porque ahora quien agrupa es
 * layerpanel.js: tener el bucle de grupos aqui, otro en emodnet.js y un
 * tercero en app.js era la misma logica tres veces, y es como se consigue que
 * un grupo ensene algo distinto de otro. */
function marineRow(l) {
  return '<label><input type="checkbox" data-marine="' + esc(l.id) + '"' +
    (MARINE.on[l.id] ? ' checked' : '') + '> ' + esc(l.name) + '</label>' +
    '<p class="note sub-opt">' + esc(l.why) + '</p>' +
    /* El instante que se esta pintando, solo si la capa esta encendida. */
    (MARINE.on[l.id]
      ? '<p class="note sub-opt">' +
        esc(t('cm_at', { t: marineTimeFor(l).slice(0, 16).replace('T', ' ') + 'Z' })) +
        (marineHas(l, marineCursor()) ? '' : ' · ' + esc(t('cm_outside'))) +
        '</p>' : '') +
    /* La escala solo cuando la capa esta encendida. Veinte leyendas a la vez
     * son ruido; la de lo que estas mirando es el dato. */
    (MARINE.on[l.id] && l.legend ? marineLegend(l) : '');
}

/* Lo que hay que decir una vez por grupo, no por capa. */
function marineGroupNote(group) {
  if (!MARINE.cat) { return ''; }
  /* El error de la corriente, donde se enciende la corriente. */
  if (group === 'currents' || group === 'reanalysis' || group === 'currents_global') {
    return '<p class="note caution-note">' + esc(MARINE.cat.caveat) + '</p>';
  }
  return '';
}

function bindMarineRows(box) {
  box.querySelectorAll('[data-marine]').forEach(function (cb) {
    cb.addEventListener('change', function () {
      marineOn(cb.dataset.marine, cb.checked);
    });
  });
}
