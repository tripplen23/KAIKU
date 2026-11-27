/* layerpanel.js - las capas del mapa, agrupadas, plegables y buscables.
 *
 * EL PROBLEMA QUE RESUELVE.
 *
 * Habia unas sesenta casillas en un scroll continuo, pintadas desde CUATRO
 * sitios distintos: las del build (app.js), las veintidos de Copernicus Marine
 * (marine.js), las doce de EMODnet (emodnet.js) y ocho escritas a mano en
 * index.html. Cuatro listas planas y tres bucles de agrupacion haciendo lo
 * mismo. Encontrar una capa concreta era recorrerlas.
 *
 * LA REGLA DE LOS TRES CLICS. Pestana -> desplegar grupo -> encender la capa.
 * Nada queda mas lejos. Y el buscador la rebaja a uno mas dos letras, que para
 * sesenta capas es lo que de verdad se usa.
 *
 * DOS EJES, NO UNO.
 *
 *   por tema    que pregunta responde la capa. Es el defecto porque un
 *               operador busca «los cables», no «lo de EMODnet».
 *   por fuente  quien la publica. Es lo que se mira al justificar una
 *               licencia o al explicar la procedencia a un jurado.
 *
 * Son dos vistas del MISMO catalogo, no dos listas: cambiar de eje cambia una
 * clave de agrupacion y nada mas. Tener las dos cuesta una linea y evita la
 * discusion de cual es la buena, porque depende de la pregunta.
 *
 * FILAS PRESTADAS. Ocho capas llevan sus propios escuchadores y su propio
 * estado (el seguidor del cursor de Sentinel, el estado de la costa HELCOM,
 * las leyendas WMS). Esas NO se vuelven a dibujar: se MUEVEN al grupo que les
 * toca. Volver a crearlas perderia los escuchadores que app.js les ato al
 * arrancar, y el fallo apareceria como «la casilla ya no hace nada».
 */
'use strict';

var LP = { axis: 'theme', q: '', open: {}, cat: [] };

/* Los grupos, en el orden en que se enseñan. El orden es una decision de
 * producto: arriba lo que se mira en una revision, abajo el fondo. */
var LP_THEMES = ['alerts', 'vessels', 'gnss', 'infra', 'seafloor', 'defence',
                 'baseline', 'forcing', 'imagery', 'basemap'];
var LP_SOURCES = ['custody', 'fintraffic', 'gnssfi', 'gpsjam', 'copernicus',
                  'cmems', 'emodnet', 'helcom', 'osm', 'vayla', 'aishub',
                  'gfw'];

/* ------------------------------------------------------------- catalogo */
/* Una entrada por capa encendible. `dom` presta una fila que ya existe en el
 * HTML; `row` la dibuja. Nada mas: el resto lo decide el agrupador. */
function lpBuild() {
  var c = [];
  var add = function (o) { c.push(o); };

  /* --- las del build, con sus temas y fuentes reales */
  var BUILD = [
    ['alerts',        'alerts',   'custody'],
    ['exposure',      'alerts',   'custody'],
    ['suppressed',    'alerts',   'custody'],
    ['sar_detections','imagery',  'custody'],
    ['sar_confirm',   'imagery',  'custody'],
    ['route',         'vessels',  'custody'],
    ['fleet',         'vessels',  'custody'],
    ['ais_coverage',  'vessels',  'custody'],
    ['tracks',        'vessels',  'fintraffic'],
    ['snapshot',      'vessels',  'fintraffic'],
    ['isobaths',      'seafloor', 'emodnet'],
    ['military_areas','defence',  'helcom'],
    ['munitions',     'defence',  'helcom'],
    ['wrecks',        'defence',  'helcom'],
    ['msp_restricted','defence',  'helcom'],
    ['anchor_ban',    'defence',  'vayla'],
    ['restrictions',  'defence',  'vayla'],
    ['corridors',     'infra',    'osm'],
    ['corridors_other','infra',   'osm'],
    ['ports',         'infra',    'osm'],
    ['scenes',        'imagery',  'copernicus'],
    ['gfw_events',    'vessels',  'gfw'],
    ['gfw_grid',      'vessels',  'gfw'],
    ['aishub',        'vessels',  'aishub'],
    /* Interferencia de la navegacion por satelite. Dos fuentes, y van en
     * grupos de FUENTE distintos a proposito: miden cosas distintas y
     * mezclarlas invitaria a leer una como confirmacion de la otra. */
    ['gnss_stations',   'gnss',   'gnssfi'],
    ['gps_interference','gnss',   'gpsjam'],
    /* El contorno va DEBAJO de los hexagonos en la lista y DEBAJO en
     * el mapa: es el fondo contra el que se leen. */
    ['gps_interference_coverage','gnss', 'gpsjam']
  ];
  BUILD.forEach(function (b) {
    add({ id: b[0], theme: b[1], source: b[2], kind: 'build',
          name: layerName(b[0]),
          why: LAYER_NOTES[b[0]] ? t(LAYER_NOTES[b[0]]) : '',
          row: function () {
            var r = renderLayerRows([[b[0], layerName(b[0])]]);
            /* UNA CAPA QUE ESTE BUILD NO PRODUJO SE DICE, no se deja en
             * blanco. renderLayerRows devuelve vacio cuando no hay capa ni
             * trabajo pendiente, y eso dejaba una fila hueca en el panel:
             * indistinguible de que la capa no exista. La razon literal la
             * tiene el manifest -- «GFW_TOKEN missing from secrets.env» -- y
             * es exactamente lo que hay que leer para arreglarlo. */
            return r || lpMissingRow(b[0]);
          } });
  });

  /* --- las prestadas: fila ya existente en el HTML, se mueve, no se recrea */
  /* El nombre va AQUI, no leido del DOM. Dos de estas filas llevan su texto
   * escrito a mano en el HTML y sin `data-i18n`, asi que leerlo del nodo las
   * dejaba sin nombre -- y una fila sin nombre no se puede buscar, que es
   * medio panel. */
  [['depthmap',    'seafloor', 'custody',    'row-depthmap',   t('dm_layer')],
   ['osm_tiles',   'basemap',  'osm',        'row-osm',        'OSM basemap'],
   ['coasthd',     'basemap',  'helcom',     'row-coasthd',    t('coast_layer')],
   ['emodnet_wms', 'seafloor', 'emodnet',    'row-emodnetwms', 'EMODnet bathymetry WMS'],
   ['s1',          'imagery',  'copernicus', 'row-s1',         t('s1_layer')],
   ['s2',          'imagery',  'copernicus', 'row-s2',         t('s2_layer')],
   ['gfw_live',    'vessels',  'gfw',        'row-gfw',        t('gfw_layer')],
   ['gfwgrid_live','vessels',  'gfw',        'row-gfwgrid',    t('gfwgrid_layer')]
  ].forEach(function (d) {
    add({ id: d[0], theme: d[1], source: d[2], kind: 'dom', dom: d[3],
          name: d[4], why: '' });
  });

  /* --- Copernicus Marine. El grupo de la capa es su tema dentro del eje
   * «tema»; en el eje «fuente» van todas juntas, que es el punto. */
  var CM_THEME = { currents: 'forcing', currents_global: 'forcing',
                   waves: 'forcing', ice: 'forcing', water: 'forcing',
                   reanalysis: 'forcing' };
  (((window.MARINE || {}).cat || {}).layers || []).forEach(function (l) {
    add({ id: l.id, theme: CM_THEME[l.group] || 'forcing', source: 'cmems',
          kind: 'marine', sub: l.group, name: l.name, why: l.why,
          on: function () { return !!MARINE.on[l.id]; },
          row: function () { return marineRow(l); } });
  });

  /* --- EMODnet */
  var EM_THEME = { baseline: 'baseline', climatology: 'baseline',
                   infrastructure: 'infra' };
  (((window.EMOD || {}).cat || {}).layers || []).forEach(function (l) {
    add({ id: l.id, theme: EM_THEME[l.group] || 'baseline', source: 'emodnet',
          kind: 'emodnet', sub: l.group, name: l.name, why: l.why,
          on: function () { return !!EMOD.on[l.id]; },
          row: function () { return emodRow(l); } });
  });

  LP.cat = c;
  return c;
}

/* La fila de una capa ausente: apagada, con su razon literal. Es la misma
 * regla que sigue el panel de salud -- una capa vacia se declara con su motivo
 * en vez de esconderse o rellenarse con un marcador. */
function lpMissingRow(id) {
  var m = (window.manifest && manifest.layers && manifest.layers[id]) || null;
  var why = m ? (m.note || m.status) : t('lp_notbuilt');
  return '<label class="lp-dead"><input type="checkbox" disabled> ' +
    esc(layerName(id)) + ' <span class="note">(' +
    esc(m ? m.status : t('lp_absent')) + ')</span></label>' +
    '<p class="note sub-opt">' + esc(why) + '</p>';
}

/* ¿Esta encendida? Se pregunta al mapa, no a una variable propia: la capa se
 * puede apagar desde el popup o desde la leyenda y el panel tiene que
 * enterarse igual. */
function lpOn(e) {
  if (e.on) { return e.on(); }
  if (e.kind === 'dom') {
    var el = document.getElementById(e.dom);
    var cb = el && el.querySelector('input[type=checkbox]');
    return !!(cb && cb.checked);
  }
  var lyr = window.layers && layers[e.id];
  return !!(lyr && map.hasLayer(lyr));
}

/* El buscador. Mira nombre, explicacion y fuente: escribir «cable» tiene que
 * encontrar los corredores de OSM Y los de EMODnet, que se llaman distinto. */
function lpMatch(e) {
  if (!LP.q) { return true; }
  var q = LP.q.toLowerCase();
  return (e.name + ' ' + (e.why || '') + ' ' + e.id + ' ' +
          t('lp_src_' + e.source) + ' ' + t('lp_th_' + e.theme))
         .toLowerCase().indexOf(q) >= 0;
}

function lpOpen(k) {
  if (LP.open[k] !== undefined) { return LP.open[k]; }
  var v = false;
  try {
    var s = localStorage.getItem('custody.lp.' + k);
    if (s !== null) { v = s === '1'; }
  } catch (err) {}
  LP.open[k] = v;
  return v;
}
function lpSetOpen(k, v) {
  LP.open[k] = v;
  try { localStorage.setItem('custody.lp.' + k, v ? '1' : '0'); } catch (err) {}
}

/* ---------------------------------------------------------------- render */
function renderLayerPanel() {
  var box = document.getElementById('layer-panel');
  if (!box || typeof layerName !== 'function') { return; }
  lpBuild();

  /* Las prestadas se sacan del panel ANTES de reescribirlo, a su almacen, o
   * el innerHTML se las llevaria por delante con sus escuchadores. */
  var store = document.getElementById('layer-rows');
  LP.cat.forEach(function (e) {
    if (e.kind !== 'dom') { return; }
    var el = document.getElementById(e.dom);
    if (el && el.parentNode !== store) { store.appendChild(el); }
  });

  var keys = LP.axis === 'theme' ? LP_THEMES : LP_SOURCES;
  var pre = LP.axis === 'theme' ? 'lp_th_' : 'lp_src_';
  var groups = {};
  LP.cat.forEach(function (e) {
    var k = e[LP.axis === 'theme' ? 'theme' : 'source'];
    (groups[k] = groups[k] || []).push(e);
  });

  var nOn = LP.cat.filter(lpOn).length;
  var h = '<div class="lp-bar">' +
    '<input type="search" id="lp-q" placeholder="' + esc(t('lp_search')) +
      '" value="' + esc(LP.q) + '" autocomplete="off">' +
    '<span class="lp-axis">' +
      ['theme', 'source'].map(function (a) {
        return '<button class="btn' + (LP.axis === a ? ' primary' : '') +
          '" data-axis="' + a + '">' + esc(t('lp_by_' + a)) + '</button>';
      }).join('') + '</span></div>' +
    '<p class="note lp-sum">' + esc(t('lp_sum', { n: nOn, m: LP.cat.length })) +
      (nOn ? ' <button class="btn lp-clear" id="lp-off">' + esc(t('lp_off')) +
        '</button>' : '') + '</p>';

  var shown = 0;
  keys.forEach(function (k) {
    var rows = (groups[k] || []).filter(lpMatch);
    if (!rows.length) { return; }
    shown += rows.length;
    var on = rows.filter(lpOn).length;
    /* Buscando se abre todo: si has escrito «cable», esconder el resultado
     * detras de un triangulo es exactamente lo contrario de buscar. */
    var op = LP.q ? true : lpOpen(k);
    h += '<details class="lp-g"' + (op ? ' open' : '') + ' data-lp="' + k + '">' +
      '<summary><span class="lp-n">' + esc(t(pre + k)) + '</span>' +
      '<span class="lp-c">' + rows.length + '</span>' +
      (on ? '<span class="lp-on">' + esc(t('lp_n_on', { n: on })) + '</span>' : '') +
      '</summary><div class="lp-body" data-body="' + k + '">' +
      '<p class="note lp-note">' + esc(t(pre + k + '_note')) + '</p>';
    /* Subgrupo dentro del grupo cuando la capa lo declara (Copernicus Marine
     * y EMODnet traen el suyo). Tercer nivel SOLO donde hace falta: con
     * veintidos capas de forzamiento, una lista plana no es accesible. */
    var subs = [], bySub = {};
    rows.forEach(function (e) {
      var sk = e.sub || '';
      if (!bySub[sk]) { bySub[sk] = []; subs.push(sk); }
      bySub[sk].push(e);
    });
    subs.forEach(function (sk) {
      if (sk) {
        h += '<h4 class="lp-sub">' + esc(t('cm_g_' + sk) !== 'cm_g_' + sk
          ? t('cm_g_' + sk) : t('em_g_' + sk)) + '</h4>';
      }
      bySub[sk].forEach(function (e) {
        h += '<div class="lp-row" data-row="' + esc(e.id) + '">' +
          (e.kind === 'dom' ? '' : e.row()) + '</div>';
      });
      if (sk && window.marineGroupNote) { h += marineGroupNote(sk); }
      if (sk && window.emodGroupNote) { h += emodGroupNote(sk); }
    });
    h += '</div></details>';
  });
  if (!shown) {
    h += '<p class="note empty">' + esc(t('lp_nohit', { q: LP.q })) + '</p>';
  }
  box.innerHTML = h;

  /* Y ahora las prestadas vuelven, cada una a su sitio. */
  LP.cat.forEach(function (e) {
    if (e.kind !== 'dom') { return; }
    var slot = box.querySelector('[data-row="' + e.id + '"]');
    var el = document.getElementById(e.dom);
    if (slot && el) { slot.appendChild(el); }
  });

  lpBind(box);
}

function lpBind(box) {
  var q = document.getElementById('lp-q');
  if (q) {
    q.addEventListener('input', function () {
      LP.q = q.value.trim();
      renderLayerPanel();
      var again = document.getElementById('lp-q');
      /* Reescribir el panel se lleva el foco con el; devolverlo al final del
       * texto es lo que permite seguir escribiendo sin mirar. */
      if (again) { again.focus(); again.setSelectionRange(again.value.length,
                                                          again.value.length); }
    });
  }
  box.querySelectorAll('[data-axis]').forEach(function (b) {
    b.addEventListener('click', function () {
      LP.axis = b.dataset.axis;
      try { localStorage.setItem('custody.lp.axis', LP.axis); } catch (e) {}
      renderLayerPanel();
    });
  });
  var off = document.getElementById('lp-off');
  if (off) { off.addEventListener('click', lpAllOff); }
  box.querySelectorAll('details.lp-g').forEach(function (d) {
    d.addEventListener('toggle', function () {
      if (!LP.q) { lpSetOpen(d.dataset.lp, d.open); }
    });
  });
  bindLayerRows(box);
  if (window.bindMarineRows) { bindMarineRows(box); }
  if (window.bindEmodRows) { bindEmodRows(box); }
}

/* «Apagar todo» existe porque encender capas es facil y acordarse de cual
 * dejaste puesta no. Con sesenta, llegar a un mapa limpio tiene que ser un
 * clic y no sesenta. */
function lpAllOff() {
  LP.cat.slice().forEach(function (e) {
    if (!lpOn(e)) { return; }
    if (e.kind === 'marine') { marineOn(e.id, false); return; }
    if (e.kind === 'emodnet') { emodOn(e.id, false); return; }
    if (e.kind === 'dom') {
      var el = document.getElementById(e.dom);
      var cb = el && el.querySelector('input[type=checkbox]');
      if (cb && cb.checked) { cb.checked = false;
        cb.dispatchEvent(new Event('change', { bubbles: true })); }
      return;
    }
    var lyr = window.layers && layers[e.id];
    if (lyr && map.hasLayer(lyr)) { map.removeLayer(lyr); }
  });
  renderLayerPanel();
}

function lpInit() {
  try {
    var a = localStorage.getItem('custody.lp.axis');
    if (a === 'theme' || a === 'source') { LP.axis = a; }
  } catch (e) {}
  renderLayerPanel();
}
