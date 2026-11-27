/* emodnet.js - la linea base de trafico de todo el AOI.
 *
 * QUE CONTESTA, Y POR QUE NINGUNA OTRA CAPA LO HACE.
 *
 * Nuestra grabacion cubre el 21 % del AOI. Sobre el resto la herramienta no
 * puede decir si lo que ve es raro, porque no sabe que es normal ahi. Estas
 * capas son ese fondo, construido con AIS que no tenemos y cubriendo el mar
 * entero. No dicen que pasa ahora --- son mensuales y agregadas--- dicen por
 * donde se pasa siempre.
 *
 * WMS Y NO WMTS, asi que Leaflet las pide por recuadro (L.tileLayer.wms) y van
 * directas al servicio. Solo la leyenda pasa por el proxy, para pedirla una vez.
 *
 * EL INSTANTE SE ELIGE DE LA LISTA, NO SE REDONDEA. EMODnet declara cada mes
 * disponible uno por uno, y fuera de esa lista el servicio devuelve una tesela
 * vacia --- que sobre el mapa se lee como «por aqui no pasa nadie», que es
 * justo lo contrario de lo que esta capa existe para decir. Asi que se busca
 * el instante declarado mas cercano al cursor y se pide ese, diciendo cual es.
 */
'use strict';

var EMOD = { cat: null, on: {}, at: {} };

function loadEmodnet(cat) {
  EMOD.cat = cat;
  if (window.renderLayerPanel) { renderLayerPanel(); }
  return cat;
}

function emodById(id) {
  var L = (EMOD.cat && EMOD.cat.layers) || [];
  for (var i = 0; i < L.length; i += 1) { if (L[i].id === id) { return L[i]; } }
  return null;
}

/* El instante DECLARADO mas cercano al cursor, y si hubo que alejarse. Lo
 * segundo importa tanto como lo primero: mirar noviembre de 2026 contra un
 * mapa de diciembre de 2024 es legitimo, pero hay que saberlo. */
function emodPick(def, at) {
  var w = def && def.time;
  if (!w || !w.values || !w.values.length) { return null; }
  var t = at === undefined
    ? ((typeof TIME !== 'undefined' && TIME.cursor !== null) ? TIME.cursor : Date.now())
    : at;
  var best = null, bestD = Infinity;
  for (var i = 0; i < w.values.length; i += 1) {
    var v = Date.parse(w.values[i]);
    var d = Math.abs(v - t);
    if (d < bestD) { bestD = d; best = w.values[i]; }
  }
  return { time: best, off_ms: bestD };
}

function emodLayer(def) {
  var p = emodPick(def);
  var opts = { layers: def.wms_layer, format: 'image/png', transparent: true,
               /* 0,55 y no 0,7: es FONDO. A 0,7 las lineas rojas de la
                * densidad competian con los circulos de alerta y con los
                * buques, que es justo lo que tiene que quedar encima. */
               version: '1.3.0', opacity: 0.55, zIndex: 15,
               attribution: EMOD.cat.attribution };
  if (p) { opts.time = p.time; }
  return L.tileLayer.wms(def.wms, opts);
}

function emodOn(id, on) {
  var def = emodById(id);
  if (!def) { return; }
  if (!on) {
    if (EMOD.on[id]) { map.removeLayer(EMOD.on[id]); delete EMOD.on[id]; }
    delete layers[id];
    delete EMOD.at[id];
    if (window.renderLayerPanel) { renderLayerPanel(); }
    return;
  }
  if (EMOD.on[id]) { return; }
  var lyr = emodLayer(def);
  lyr.addTo(map);
  /* Debajo de los buques y las alertas: es fondo, no primer plano. */
  if (lyr.bringToBack) { lyr.bringToBack(); }
  EMOD.on[id] = lyr;
  layers[id] = lyr;
  var p = emodPick(def);
  EMOD.at[id] = p ? p.time : null;
  if (window.renderLayerPanel) { renderLayerPanel(); }
}

/* Al mover el cursor, repintar solo si cambia el MES elegido. Un mapa mensual
 * no cambia porque el cursor avance diez minutos. */
function emodFollowCursor() {
  var any = false;
  Object.keys(EMOD.on).forEach(function (id) {
    var def = emodById(id);
    if (!def || !def.time) { return; }
    var p = emodPick(def);
    if (!p || EMOD.at[id] === p.time) { return; }
    EMOD.at[id] = p.time;
    EMOD.on[id].setParams({ time: p.time });
    any = true;
  });
  if (any && window.renderLayerPanel) { renderLayerPanel(); }
}

function emodLegend(l) {
  var u = (window.PROXY && PROXY.on)
    ? '/cache/img?u=' + encodeURIComponent(l.legend) : l.legend;
  return '<div class="cm-legend"><img src="' + esc(u) + '" alt="' +
    esc(t('em_scale', { n: l.name })) + '" loading="lazy">' +
    '<div class="cm-legend-t"><div class="k">' +
    esc(l.service_title || l.name) + '</div></div></div>';
}

/* UNA FILA, una capa. Ver marine.js: quien agrupa es layerpanel.js. */
function emodRow(l) {
  var p = EMOD.on[l.id] ? emodPick(l) : null;
  return '<label><input type="checkbox" data-emod="' + esc(l.id) + '"' +
    (EMOD.on[l.id] ? ' checked' : '') + '> ' + esc(l.name) + '</label>' +
    '<p class="note sub-opt">' + esc(l.why) + '</p>' +
    /* El instante que se esta pintando y a que distancia del cursor. Una capa
     * mensual junto a un cursor al minuto necesita decirlo. */
    (p ? '<p class="note sub-opt ' +
          (p.off_ms > 45 * 86400e3 ? 'caution-note' : '') + '">' +
          esc(t('em_at', { d: p.time.slice(0, 7), a: fmtDur(p.off_ms) })) +
          '</p>' : '') +
    (EMOD.on[l.id] && l.legend ? emodLegend(l) : '');
}

function emodGroupNote(group) {
  /* El aviso de 2024 va donde se enciende la climatologia, que es a quien
   * afecta: la de EMSA no lo sufre. */
  return (group === 'climatology' && EMOD.cat)
    ? '<p class="note caution-note">' + esc(EMOD.cat.caveat) + '</p>' : '';
}

function bindEmodRows(box) {
  box.querySelectorAll('[data-emod]').forEach(function (cb) {
    cb.addEventListener('change', function () { emodOn(cb.dataset.emod, cb.checked); });
  });
}
