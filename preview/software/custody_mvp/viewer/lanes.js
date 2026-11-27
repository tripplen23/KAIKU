/* lanes.js - una pista por fuente de datos, agrupadas y plegables.
 *
 * QUE PREGUNTA CONTESTA.
 *
 * «¿Puedo superponer estas dos capas en el mismo instante?» Antes habia que
 * saberselo de memoria: el AIS estaba en una pista, las pasadas Sentinel en
 * otra, y la cadencia de los modelos en ningun sitio. Con el eje de tiempos
 * de cada fuente dibujado uno encima de otro, el solape se ve de un vistazo
 * y deja de ser una suposicion.
 *
 * LAS VENTANAS SE LEEN, NO SE ESCRIBEN A MANO.
 *
 *   AIS       del polllog, que registra cuando sondeabamos de verdad
 *   Sentinel  del catalogo STAC ya cargado en el navegador
 *   CMEMS     de la dimension `time` que declara su WMTS
 *   FMI       del eje de tiempos que viene en su propia respuesta
 *
 * Una cadencia escrita a mano es una que se queda vieja sin avisar: asi
 * estabamos pidiendo medias DIARIAS de corriente creyendo que eran horarias.
 *
 * TRES CLASES DE PISTA, porque son tres cosas distintas:
 *   windows  intervalos medidos en los que hubo dato (AIS)
 *   ticks    instantes sueltos (una pasada de satelite)
 *   span     un intervalo continuo con paso declarado (un modelo)
 * Y `static`, para lo que no tiene eje temporal: una costa o un cable estan
 * siempre, y decirlo evita buscarles una ventana que no existe.
 */
'use strict';

var LANES = { srv: null, open: {}, err: null, loading: false };

var LANE_GROUPS = [
  { key: 'ours',     cls: 'lg-ours' },
  { key: 'imagery',  cls: 'lg-img' },
  { key: 'baseline', cls: 'lg-base' },
  { key: 'forcing',  cls: 'lg-forc' },
  { key: 'static',   cls: 'lg-stat' }
];

/* Plegado recordado. El panel de tiempo se repinta constantemente, asi que
 * sin esto cada repintado volveria a abrir lo que acabas de cerrar -- el
 * mismo fallo que tuvo el panel «What you are looking at». */
function lanesOpen(k) {
  if (LANES.open[k] !== undefined) { return LANES.open[k]; }
  var v = true;
  try {
    var s = localStorage.getItem('custody.lanes.' + k);
    if (s !== null) { v = s === '1'; }
  } catch (e) {}
  /* Por defecto abiertas las dos de arriba: son las que gobiernan una
   * revision. Forzamiento y estatico se abren cuando hacen falta. */
  if (LANES.open[k] === undefined &&
      (k === 'forcing' || k === 'static' || k === 'baseline')) {
    try { if (localStorage.getItem('custody.lanes.' + k) === null) { v = false; } }
    catch (e) { v = false; }
  }
  LANES.open[k] = v;
  return v;
}
function lanesSetOpen(k, v) {
  LANES.open[k] = v;
  try { localStorage.setItem('custody.lanes.' + k, v ? '1' : '0'); } catch (e) {}
}

function lanesLoad() {
  if (LANES.loading) { return Promise.resolve(); }
  LANES.loading = true;
  return fetch('/sources/time').then(function (r) {
    if (!r.ok) { throw new Error('HTTP ' + r.status); }
    return r.json();
  }).then(function (d) {
    LANES.srv = d; LANES.err = null; LANES.loading = false;
    /* De paso viene donde vive el almacen y si hay grabacion fuera de el.
     * Lo pinta el panel de salud: una herramienta que no sabe donde estan sus
     * datos no puede responder por ellos. */
    if (window.STORES) {
      STORES.roots = d.stores || [];
      STORES.strays = d.strays || [];
      if (window.renderHealth && window.manifest) { renderHealth(); }
    }
    if (window.renderTimeBar && TIME.t1) { renderTimeBar(); }
  }).catch(function (e) {
    LANES.err = e.message; LANES.loading = false;
  });
}

/* --------------------------------------------------------------- modelo */
/* Una pista por fuente. El orden dentro de cada grupo es deliberado: primero
 * lo que mas se mira. */
function laneModel() {
  var g = { ours: [], imagery: [], baseline: [], forcing: [], static: [] };

  /* --- lo nuestro. La pista de AIS sale de TIME.win, que ya se refresca
   * desde /coverage sin recompilar. */
  /* La ultima ventana llega hasta el fix mas nuevo QUE CONOCE EL VISOR.
   * /coverage sale del polllog y se refresca cada cinco minutos, mientras el
   * cursor sigue al dato en vivo: sin esto, durante esos minutos el cursor
   * caia justo despues del final de la ventana y la pista mas importante de
   * todas se contaba como «sin dato aqui». */
  var win = (TIME.win || []).slice();
  if (win.length && window.LIVEV && LIVEV.newest &&
      LIVEV.newest > win[win.length - 1][1]) {
    win[win.length - 1] = [win[win.length - 1][0], LIVEV.newest];
  }
  g.ours.push({ id: 'ais', cls: 'ais', name: t('lane_ais'), kind: 'windows',
                marks: win, step_s: 60, licence: 'CC BY 4.0',
                /* Hasta donde hay BUQUES Y ALERTAS, no solo cobertura. Lo
                 * que quede mas alla se dibuja hueco: sabemos que estabamos
                 * escuchando y el AIS crudo esta en disco, pero nadie lo ha
                 * evaluado. Antes ese borde era el del build; ahora es el
                 * del motor, que normalmente llega al presente, asi que la
                 * parte hueca solo aparece cuando de verdad falta algo ---
                 * sin motor, o con un hueco mayor que su ventana. */
                solidTo: liveEdge() });

  (((LANES.srv || {}).sources) || []).forEach(function (s) {
    if (s.id === 'ais_fintraffic') { return; }        /* ya esta arriba */
    var lane = { id: s.id, cls: 'src-' + s.id, name: s.name, note: s.note,
                 state: s.state, step_s: s.step_s, licence: s.licence,
                 forecast: s.forecast };
    if (s.kind === 'windows') {
      lane.kind = 'windows'; lane.marks = s.windows_ms || [];
    } else {
      lane.kind = 'span'; lane.start = s.start_ms; lane.end = s.end_ms;
    }
    /* La ventana evaluada avanza con cada ciclo del motor, y /sources/time se
     * cachea dos minutos: sin esto la pista se quedaba un par de minutos
     * corta y el cursor, que SI esta en el ultimo fix, caia fuera de ella. */
    if (s.id === 'alerts_live' && window.LIVEV && LIVEV.newest && lane.marks.length) {
      var w = lane.marks[lane.marks.length - 1];
      if (LIVEV.newest > w[1]) { w[1] = LIVEV.newest; }
    }
    (g[s.group] || g.ours).push(lane);
  });

  /* --- imagenes: el catalogo STAC ya esta en el navegador */
  if (window.PASSES && PASSES.loaded) {
    g.imagery.push({ id: 's1', cls: 's1', name: t('lane_s1'), kind: 'ticks',
                     marks: PASSES.s1, licence: 'Copernicus' });
    g.imagery.push({ id: 's2', cls: 's2', name: t('lane_s2'), kind: 'ticks',
                     marks: PASSES.s2, licence: 'Copernicus' });
  } else {
    g.imagery.push({ id: 's1', cls: 's1', name: t('lane_s1'), kind: 'ticks',
                     marks: [], state: 'loading' });
  }

  /* --- forzamiento: CMEMS, agrupado por CONJUNTO DE DATOS y no por capa.
   * Veinte pistas serian ruido, y ademas serian redundantes: las capas que
   * comparten dataset comparten eje temporal por definicion. Tres pistas
   * dicen lo mismo sin repetirlo. */
  var cm = {};
  (((window.MARINE || {}).cat || {}).layers || []).forEach(function (l) {
    if (!l.time || !l.time.start_ms) { return; }
    var ds = String(l.layer).split('/')[1] || l.id;
    if (!cm[ds]) {
      cm[ds] = { id: 'cmems_' + ds, cls: 'cmems', kind: 'span',
                 start: l.time.start_ms, end: l.time.end_ms, step_s: l.step_s,
                 licence: 'Copernicus Marine', vars: [], groups: {} };
    }
    cm[ds].vars.push(l.name);
    cm[ds].groups[l.group] = 1;
  });
  Object.keys(cm).sort().forEach(function (k) {
    var l = cm[k];
    /* El nombre dice QUE trae y a que paso. Nombrarlas solo por la cadencia
     * daba dos pistas llamadas «CMEMS 1 h» --- oleaje y hielo--- que es
     * justo lo que no se puede distinguir de un vistazo. */
    /* Nombres cortos para las pistas, no la clave del grupo. «CMEMS
     * currents_global» se colo tal cual en la interfaz: una clave interna en
     * pantalla es una fuga, no un nombre. */
    l.name = 'CMEMS ' + Object.keys(l.groups).sort().map(function (k) {
      return ({ currents: 'current', currents_global: 'global',
                waves: 'waves', ice: 'ice', water: 'water',
                reanalysis: 'reanalysis' })[k] || k;
    }).join('/') + ' · ' + laneStepText(l.step_s);
    l.note = l.vars.length + ' layers: ' + l.vars.slice(0, 4).join(', ') +
             (l.vars.length > 4 ? '…' : '');
    g.forcing.push(l);
  });

  /* --- linea base de trafico: EMODnet. Una pista por PRODUCTO, no por capa,
   * por lo mismo que Copernicus: las capas de un producto comparten eje. Lo
   * que hay que ver aqui es el DESFASE --- que la de EMSA llega al mes pasado
   * y la de Cogea se queda en 2024-- porque decide con cual se puede comparar
   * lo que estas mirando. */
  var em = {};
  ((((window.EMOD || {}).cat) || {}).layers || []).forEach(function (l) {
    if (!l.time || !l.time.start_ms) { return; }
    var k = l.group;
    if (!em[k]) {
      em[k] = { id: 'emod_' + k, cls: 'emod', kind: 'span',
                start: l.time.start_ms, end: l.time.end_ms, step_s: l.step_s,
                licence: 'CC BY 4.0 · EMODnet + CLS', vars: [] };
    }
    em[k].start = Math.min(em[k].start, l.time.start_ms);
    em[k].end = Math.max(em[k].end, l.time.end_ms);
    em[k].vars.push(l.name);
  });
  Object.keys(em).sort().forEach(function (k) {
    var l = em[k];
    l.name = (k === 'baseline' ? 'EMSA route density' : 'Cogea vessel density') +
             ' · ' + laneStepText(l.step_s);
    l.note = l.vars.length + ' layers: ' + l.vars.join(', ');
    g.baseline.push(l);
  });

  /* --- estatico: lo que no tiene eje temporal. Una sola pista, porque la
   * respuesta para todas es la misma y repetirla once veces no informa. */
  g.static.push({ id: 'static', cls: 'stat', kind: 'static',
                  name: t('lane_static'), note: t('lane_static_note') });
  return g;
}

/* Hasta donde esta EVALUADO: lo mas lejos que llegan build o motor. */
function liveEdge() {
  var e = TIME.builtTo || 0;
  if (window.LIVEV && LIVEV.winStart && LIVEV.newest &&
      LIVEV.winStart <= e + 3600e3) {
    e = Math.max(e, LIVEV.newest);
  }
  return e;
}

function laneStepText(s) {
  if (!s) { return t('lane_step_na'); }
  if (s < 3600) { return Math.round(s / 60) + ' min'; }
  if (s < 86400) { return Math.round(s / 3600) + ' h'; }
  return Math.round(s / 86400) + ' d';
}

/* ¿Tiene dato esta fuente en este instante? Es el nucleo de la pregunta de
 * solape, asi que vive en una sola funcion y la usan tanto el recuento de la
 * cabecera como el resaltado de cada pista. */
function laneHasAt(l, at) {
  if (l.kind === 'static') { return true; }
  if (l.kind === 'span') {
    return !!(l.start && l.end && at >= l.start && at <= l.end);
  }
  if (l.kind === 'windows') {
    return (l.marks || []).some(function (w) { return at >= w[0] && at <= w[1]; });
  }
  if (l.kind === 'ticks') {
    /* Una pasada es un instante; «coincide» con una tolerancia, porque nadie
     * va a clavar el cursor en el milisegundo de la adquisicion. Media hora
     * es el mismo umbral con el que el mapa considera fresca una posicion. */
    return (l.marks || []).some(function (m) {
      return Math.abs(m.t - at) <= TIME.staleMs; });
  }
  return false;
}

/* Cuantas fuentes coinciden en el cursor. Esta es LA respuesta a «cuando
 * puedo superponer dos mapas»: si el numero es 1, no hay nada que superponer. */
function lanesAt(at) {
  var g = laneModel(), hit = [], tot = 0;
  LANE_GROUPS.forEach(function (grp) {
    (g[grp.key] || []).forEach(function (l) {
      if (l.kind === 'static') { return; }      /* siempre esta: no informa */
      tot += 1;
      if (laneHasAt(l, at)) { hit.push(l.name); }
    });
  });
  return { hit: hit, total: tot };
}

/* --------------------------------------------------------------- render */
function lanesHtml() {
  var g = laneModel();
  var cur = TIME.cursor === null ? TIME.v1 : TIME.cursor;
  var h = '';
  LANE_GROUPS.forEach(function (grp) {
    var rows = g[grp.key] || [];
    if (!rows.length) { return; }
    var withData = rows.filter(function (l) {
      return l.kind !== 'static' && laneHasAt(l, cur); }).length;
    var op = lanesOpen(grp.key);
    h += '<details class="lane-g ' + grp.cls + '"' + (op ? ' open' : '') +
      ' data-lg="' + grp.key + '"><summary>' +
      '<span class="lg-n">' + esc(t('lane_g_' + grp.key)) + '</span>' +
      '<span class="lg-c">' + rows.length + '</span>' +
      (withData ? '<span class="lg-hit">' +
        esc(t('lane_here', { n: withData })) + '</span>' : '') +
      '</summary>' +
      rows.map(laneRow).join('') + '</details>';
  });
  return h;
}

function laneRow(l) {
  var span = Math.max(1, TIME.v1 - TIME.v0);
  var pos = function (ms) { return 100 * (ms - TIME.v0) / span; };
  var cur = TIME.cursor === null ? TIME.v1 : TIME.cursor;
  var bars = '', n = 0;

  if (l.kind === 'windows') {
    (l.marks || []).forEach(function (m) {
      if (m[1] < TIME.v0 || m[0] > TIME.v1) { return; }
      var a = Math.max(m[0], TIME.v0), b = Math.min(m[1], TIME.v1);
      n += 1;
      /* Grabado pero no evaluado: hueco. Hay cobertura, pero ni el build ni
       * el motor han producido buques ni alertas de ese tramo, y pintarlo
       * lleno prometeria algo que al mover el cursor no aparece. */
      var raw = l.solidTo && a > l.solidTo;
      bars += '<i' + (raw ? ' class="raw"' : '') + ' data-t="' +
        Math.round((a + b) / 2) + '" style="left:' + pos(a) +
        '%;width:' + Math.max(0.5, pos(b) - pos(a)) + '%" title="' + fmtUTC(m[0]) +
        ' → ' + fmtUTC(m[1]) + (raw ? ' · ' + t('lane_raw_tip') : '') + '"></i>';
    });
  } else if (l.kind === 'ticks') {
    (l.marks || []).forEach(function (m) {
      if (m.t < TIME.v0 || m.t > TIME.v1) { return; }
      n += 1;
      bars += '<i class="tick" data-t="' + m.t + '" style="left:' + pos(m.t) +
        '%" title="' + fmtUTC(m.t) + (m.cloud !== undefined && m.cloud !== null
          ? ' · ' + Math.round(m.cloud) + '% cloud' : '') + '"></i>';
    });
  } else if (l.kind === 'span' && l.start && l.end) {
    /* UN PRONOSTICO QUE EMPIEZA MAS ALLA DEL BORDE DERECHO.
     *
     * Las consultas de punto de FMI arrancan en la proxima hora en punto, y
     * el deslizador termina en el ultimo fix, que siempre es anterior. O sea
     * que la pista salia VACIA --- indistinguible de «no hay dato»--- cuando
     * lo que pasa es que el dato esta fuera de la vista, en el futuro.
     * Se dibuja un tope en el borde con el horizonte en el titulo. Mover el
     * deslizador para ver el futuro no es opcion: lo acotan los datos, y
     * debe seguir acotandolo. */
    if (l.start > TIME.v1) {
      bars += '<i class="ahead" style="right:0;width:4px" data-t="' + TIME.v1 +
        '" title="' + esc(t('lane_ahead', {
          a: fmtUTC(l.start), b: fmtUTC(l.end),
          s: laneStepText(l.step_s) })) + '"></i>';
      n = 0;
    } else if (l.end < TIME.v0) {
      bars += '<i class="behind" style="left:0;width:4px" data-t="' + TIME.v0 +
        '" title="' + esc(t('lane_behind', { b: fmtUTC(l.end) })) + '"></i>';
      n = 0;
    }
    if (!(l.end < TIME.v0 || l.start > TIME.v1)) {
      var a2 = Math.max(l.start, TIME.v0), b2 = Math.min(l.end, TIME.v1);
      n = 1;
      /* La parte que cae en el FUTURO se raya: un modelo sigue dando valores
       * mas alla de ahora, y pintar pronostico igual que analisis invita a
       * leer una prevision como una medida. */
      var now = TIME.now || Date.now();
      var cut = Math.min(b2, Math.max(a2, now));
      bars += '<i style="left:' + pos(a2) + '%;width:' +
        Math.max(0.5, pos(cut) - pos(a2)) + '%" data-t="' +
        Math.round((a2 + cut) / 2) + '" title="' + fmtUTC(l.start) + ' → ' +
        fmtUTC(l.end) + ' · ' + esc(t('lane_step', { s: laneStepText(l.step_s) })) +
        '"></i>';
      if (b2 > cut) {
        bars += '<i class="fcast" style="left:' + pos(cut) + '%;width:' +
          Math.max(0.5, pos(b2) - pos(cut)) + '%" data-t="' +
          Math.round((cut + b2) / 2) + '" title="' + esc(t('lane_fcast')) +
          ' → ' + fmtUTC(l.end) + '"></i>';
      }
    }
  } else if (l.kind === 'static') {
    bars = '<i class="always" style="left:0;width:100%" title="' +
      esc(l.note || '') + '"></i>';
  }

  var cline = (cur >= TIME.v0 && cur <= TIME.v1)
    ? '<b class="lane-cur" style="left:' + pos(cur) + '%"></b>' : '';
  var here = laneHasAt(l, cur);
  var cnt = l.kind === 'static' ? '∞'
    : (l.state === 'needs_key' ? t('lane_key')
       : (l.state === 'loading' ? '…'
          /* Un cero dice «no hay dato». Si lo hay pero cae fuera de la vista,
           * eso es otra cosa y se escribe distinto. */
          : (n === 0 && l.kind === 'span' && l.start > TIME.v1 ? '→'
             : (n === 0 && l.kind === 'span' && l.end < TIME.v0 ? '←' : n))));
  var tip = [l.note, l.step_s ? t('lane_step', { s: laneStepText(l.step_s) }) : '',
             l.licence ? 'Licence: ' + l.licence : '']
            .filter(Boolean).join(' · ');
  return '<div class="lane ' + l.cls + (here ? ' lane-here' : '') +
    (l.state === 'needs_key' ? ' lane-off' : '') + '" title="' + esc(tip) + '">' +
    '<span class="lane-n">' + esc(l.name) + '</span>' +
    '<span class="lane-b" data-lane="' + esc(l.id) + '">' + bars + cline +
    '</span><span class="lane-c">' + esc(String(cnt)) + '</span></div>';
}

/* El plegado se enlaza aparte porque el panel se repinta entero y los
 * <details> nativos perderian el estado al hacerlo. */
function lanesBind(el) {
  el.querySelectorAll('details.lane-g').forEach(function (d) {
    d.addEventListener('toggle', function () {
      lanesSetOpen(d.dataset.lg, d.open);
    });
  });
}
