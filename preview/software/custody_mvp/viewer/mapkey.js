/* mapkey.js - la clave permanente del mapa.
 *
 * La leyenda flotante explica el vocabulario; esto explica LO QUE HAY EN
 * PANTALLA AHORA. Son preguntas distintas y la segunda es la que se hace
 * alguien que abre la herramienta por primera vez: que son estos triangulos,
 * de que momento son, cuantos hay.
 *
 * Por eso cuenta sobre la capa viva y no sobre el fichero: si el filtro de
 * buques esta puesto, los numeros bajan con el, que es lo correcto.
 */
'use strict';

/* Colores: los mismos literales que usan las capas. Viven aqui y alli, asi
 * que una prueba de humo los ata (ver smoke.js). */
var VESSEL_COLOURS = {
  live:     { move: '#5ce1e6', stop: '#5ce1e6' },
  snapshot: { move: '#58d68d', stop: '#44596d' },
  last:     { move: '#7fd7ff', stop: '#6a7f91' }
};
var VIEW_LAYER = { live: 'live', snapshot: 'snapshot', last: 'positions' };

/* Cuenta moviendose / parado / sin rumbo recorriendo la capa que esta en el
 * mapa. No hay otra via honesta: cada capa guarda la velocidad en un campo
 * distinto porque vienen de tres sitios. */
function countView(v) {
  var lyr = layers[VIEW_LAYER[v]];
  if (!lyr || !map.hasLayer(lyr)) { return null; }
  var c = { move: 0, stop: 0, nohdg: 0, stale: 0, total: 0 };
  lyr.eachLayer(function (l) {
    var p = l.feature ? l.feature.properties : (l._mkProps || null);
    if (!p) { p = {}; }
    var sog = p.sog_kn !== undefined ? p.sog_kn : p.sog;
    var hdg = p.heading_deg !== undefined ? p.heading_deg : p.heading;
    c.total += 1;
    if (sog !== null && sog !== undefined && sog > 0.5) { c.move += 1; } else { c.stop += 1; }
    if (hdg === null || hdg === undefined || hdg >= 360) { c.nohdg += 1; }
    if (p.stale) { c.stale += 1; }
  });
  return c;
}

function mkItem(colour, size, dim, label, n, circle) {
  return '<span class="mk-i' + (dim ? ' dim' : '') + '">' +
    '<span class="vg">' + shipIcon(circle ? null : 20, colour, size).options.html +
    '</span>' + esc(label) + (n === null ? '' : ' <b>' + n + '</b>') + '</span>';
}

/* Si el usuario la cierra, se queda cerrada. renderMapKey() se llama en cada
 * redibujado de la instantanea -- cada sondeo en vivo, cada movimiento del
 * cursor -- y ponia hidden=false sin preguntar, asi que la X duraba menos de
 * un segundo. La decision se recuerda entre sesiones: cerrar algo tres veces
 * al dia porque vuelve solo es peor que no poder cerrarlo. */
function mapKeyDismissed() {
  try { return localStorage.getItem(LS.mapkey) === 'off'; } catch (e) { return false; }
}

/* El boton «Key» de la barra superior. Cerrar algo sin un camino de vuelta
 * visible es una trampa, no una opcion. */
function mapKeyToggle() {
  var off = mapKeyDismissed();
  try { localStorage.setItem(LS.mapkey, off ? 'on' : 'off'); } catch (e) {}
  renderMapKey();
  var box = document.getElementById('mapkey');
  if (box && off) {
    box.classList.remove('flash'); void box.offsetWidth; box.classList.add('flash');
    setTimeout(function () { box.classList.remove('flash'); }, 1200);
  }
}

function renderMapKey() {
  var box = document.getElementById('mapkey'); if (!box) { return; }
  var c = countView('snapshot');
  if (!c || !c.total || mapKeyDismissed()) {
    box.innerHTML = ''; box.hidden = true; return;
  }
  box.hidden = false;
  var liveNow = typeof LIVE !== 'undefined' && LIVE.on && LIVE.follow;
  box.innerHTML = '<div class="mk-head">' + esc(t('mk_h')) +
      '<button class="xbtn" id="mk-hide" title="' + esc(t('chip_hide')) + '">&times;</button>' +
    '</div>' +
    '<div class="mk-view"><div class="mk-name">' +
      esc(t(liveNow ? 'mk_at_live' : 'mk_at_cursor')) +
      '<span class="note"> · ' + esc(fmtUTC(TIME.cursor === null ? TIME.t1 : TIME.cursor)) +
      '</span></div>' +
      '<div class="mk-items">' +
        mkItem(VESSEL_COLOURS.snapshot.move, 20, false, t('mk_moving'), c.move) +
        mkItem(VESSEL_COLOURS.snapshot.stop, 14, true, t('mk_stopped'), c.stop) +
        mkItem(VESSEL_COLOURS.snapshot.move, 20, false, t('mk_nohdg'), c.nohdg, true) +
      '</div></div>' +
    (c.stale ? '<div class="mk-note-stale">' +
      esc(t('mk_stale', { n: c.stale })) + '</div>' : '') +
    '<p class="note">' + esc(t('mk_shape')) + '</p>';
  document.getElementById('mk-hide').addEventListener('click', function () {
    try { localStorage.setItem(LS.mapkey, 'off'); } catch (e) {}
    box.innerHTML = ''; box.hidden = true;
    if (window.flashMapNote) { flashMapNote(t('mk_closed')); }
  });
}

/* Aviso efimero sobre el mapa. Se usa cuando la herramienta cambia algo por
 * su cuenta: hacerlo en silencio es peor que no hacerlo. */
/* `sticky` para avisos cuya CONDICION persiste.
 *
 * Un destello de seis segundos sirve para un suceso --- «3 alertas nuevas»---
 * pero no para un estado: «el radar esta encendido y el zoom no llega» sigue
 * siendo verdad despues del destello, y quien estuviera leyendo la lista de
 * alertas se lo pierde y vuelve a ver mar vacio sin explicacion. Un aviso
 * pegajoso se queda hasta que quien lo puso lo quita. */
function flashMapNote(msg, sticky) {
  var box = document.getElementById('mapnote'); if (!box) { return; }
  box.textContent = msg;
  box.hidden = false;
  box.classList.toggle('sticky', !!sticky);
  if (flashMapNote._t) { clearTimeout(flashMapNote._t); flashMapNote._t = null; }
  if (!sticky) {
    flashMapNote._t = setTimeout(function () { box.hidden = true; }, 6000);
  }
}

function clearMapNote(onlySticky) {
  var box = document.getElementById('mapnote'); if (!box) { return; }
  if (onlySticky && !box.classList.contains('sticky')) { return; }
  box.hidden = true;
  box.classList.remove('sticky');
}
