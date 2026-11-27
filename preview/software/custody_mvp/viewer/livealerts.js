/* livealerts.js - alertas en tiempo de ejecucion.
 *
 * El build calcula alertas sobre todo el historial. El servidor las recalcula
 * cada 60 s sobre una ventana movil de 6 h, con el MISMO motor de Python.
 * Aqui se unen las dos.
 *
 * COMO SE UNEN, Y POR QUE ASI.
 *
 * No se concatenan: se solapan. Las dos fuentes cubren el mismo tramo
 * reciente y pondrian la misma alerta dos veces. La regla es por tiempo:
 *
 *   antes del inicio de la ventana viva  ->  manda el build (es lo unico
 *                                            que tiene historial largo)
 *   dentro de la ventana viva            ->  manda el vivo (es lo unico
 *                                            que tiene los ultimos minutos)
 *
 * El corte es el inicio de la ventana del servidor, no «ahora»: dentro de
 * esa ventana el vivo es completo, asi que mezclar ahi solo duplicaria.
 *
 * NO HAY UNA SEGUNDA IMPLEMENTACION DE LOS INDICADORES EN JAVASCRIPT. Esa
 * tentacion es la que produce que la demo y el informe no coincidan. Aqui
 * solo se recibe, se une y se avisa.
 */
'use strict';

var LIVEAL = { on: false, es: null, at: 0, winStart: 0, n: 0, newN: 0,
               err: null, cycles: 0, buildOnly: null };

function liveAlertsStart() {
  if (LIVEAL.es) { return; }
  /* EventSource, no un setInterval: el valor del producto es disparar en el
   * momento en que se descubre, y preguntar cada minuto añade hasta un
   * minuto de retardo a cambio de nada. */
  try {
    LIVEAL.es = new EventSource('/events');
  } catch (e) {
    LIVEAL.err = e.message;
    return;
  }
  LIVEAL.es.addEventListener('cycle', function (ev) {
    var d = {};
    try { d = JSON.parse(ev.data); } catch (e) { return; }
    LIVEAL.cycles += 1;
    fetchLiveAlerts(d);
    /* El mismo empujon trae los BUQUES. Un ciclo del motor produce las dos
     * cosas --- alertas y trazas--- de la misma ventana, asi que pedirlas por
     * separado solo abriria la puerta a que una se adelante a la otra y una
     * alerta apunte a un buque que el mapa todavia no tiene. */
    fetchLiveVessels();
  });
  LIVEAL.es.onerror = function () {
    /* Sin servidor propio --o sirviendo con python -m http.server-- esto no
     * existe. El visor sigue con las alertas del build y lo dice. */
    LIVEAL.err = 'sin conexion de eventos';
    liveAlertsStatus();
  };
}

function fetchLiveAlerts(cycle) {
  return fetch('/alerts/live').then(function (r) {
    if (!r.ok) { throw new Error('HTTP ' + r.status); }
    return r.json();
  }).then(function (fc) {
    var feats = fc.features || [];
    if (LIVEAL.buildOnly === null) {
      /* La primera vez se guarda lo del build intacto, para poder rehacer la
       * union en cada ciclo sin ir acumulando. */
      LIVEAL.buildOnly = alertFeatures.slice();
    }
    var ts = feats.map(function (f) { return f.properties.ts_ms || 0; })
                  .filter(function (x) { return x; });
    LIVEAL.winStart = ts.length ? Math.min.apply(null, ts) : 0;
    LIVEAL.at = cycle && cycle.at ? cycle.at : Date.now();
    LIVEAL.n = feats.length;
    LIVEAL.newN = feats.filter(function (f) { return f.properties.is_new; }).length;
    LIVEAL.on = true;
    LIVEAL.err = null;
    if (cycle && cycle.sources) { LIVEAL.src = cycle.sources; }
    /* La ventana que DECLARA el motor, no la deducida del alerta mas vieja:
     * con pocas alertas la deduccion encogia la ventana y decia «2 h» sobre
     * una de doce. */
    if (cycle && cycle.window_h) { LIVEAL.winH = cycle.window_h; }
    if (cycle && cycle.trigger) { LIVEAL.trigger = cycle.trigger; }

    var viejas = LIVEAL.buildOnly.filter(function (f) {
      return (f.properties.ts_ms || 0) < LIVEAL.winStart;
    });
    feats.forEach(function (f) { f.properties.live = true; });
    alertFeatures = viejas.concat(feats);

    if (window.refreshAlertViews) { refreshAlertViews(); }
    liveAlertsStatus();
    /* Avisar solo de lo que es nuevo DE VERDAD. Repetir el aviso en cada
     * ciclo es como se consigue que el operador deje de mirarlos. */
    if (LIVEAL.newN && LIVEAL.cycles > 1 && window.flashMapNote) {
      flashMapNote(t('la_new', { n: LIVEAL.newN }));
    }
    return feats.length;
  }).catch(function (e) {
    LIVEAL.err = e.message; LIVEAL.on = false; liveAlertsStatus();
  });
}

/* Las trazas de la ventana viva, fusionadas en el HIST del visor.
 *
 * `since` pide solo lo que el build no tiene: enviar de nuevo las horas ya
 * compiladas seria pagar ancho de banda por datos que ya estan en memoria.
 * Se deja media hora de solape para no partir una derrota justo en el corte.
 */
function fetchLiveVessels() {
  /* SOLO LA COLA, a partir de la segunda vez.
   *
   * La primera peticion trae la ventana entera --- lo que el build no tiene,
   * 5,7 MB en claro, 1,2 comprimido. Pedir eso otra vez en cada ciclo seria
   * mover 6 MB por minuto para descubrir, al fusionar, que el 99 % ya estaba
   * en memoria. A partir de ahi se pide desde el ultimo fix conocido con
   * media hora de solape: el solape es gratis porque la fusion deduplica por
   * marca de tiempo, y evita que una derrota se parta justo en el corte.
   */
  var since = (typeof TIME !== 'undefined' && TIME.builtTo)
    ? TIME.builtTo - 1800e3 : 0;
  if (window.LIVEV && LIVEV.newest) {
    since = Math.max(since, LIVEV.newest - 1800e3);
  }
  return fetch('/vessels/live' + (since ? '?since=' + since : ''))
    .then(function (r) {
      if (!r.ok) { throw new Error('HTTP ' + r.status); }
      return r.json();
    }).then(function (fc) {
      if (!window.mergeLiveTracks) { return 0; }
      var st = mergeLiveTracks(fc);
      /* Repintar solo si llego algo. Reconstruir la instantanea en cada
       * ciclo sin fixes nuevos es trabajo por nada. */
      if (st.added && window.renderTimeBar) {
        if (window.setCursor && LIVE && LIVE.follow && LIVEV.newest) {
          setCursor(LIVEV.newest, false, true);
        } else {
          renderTimeBar();
        }
        if (window.renderVesselTab) { renderVesselTab(''); }
      }
      return st.added;
    }).catch(function (e) {
      if (window.LIVEV) { LIVEV.err = e.message; }
    });
}

function liveAlertsStatus() {
  var el = document.getElementById('live-alerts'); if (!el) { return; }
  if (LIVEAL.on) {
    el.className = 'note la-on';
    el.innerHTML = esc(t('la_on', {
      n: LIVEAL.n,
      w: LIVEAL.winH ? LIVEAL.winH.toFixed(1)
        : Math.round((Date.now() - LIVEAL.winStart) / 3600e3),
      t: fmtUTC(LIVEAL.at)
    })) +
    (LIVEAL.trigger ? '<span class="la-src">' +
      esc(t('la_trigger', { x: LIVEAL.trigger })) + '</span>' : '') +
    /* De que fuentes salen. Un operador tiene que poder decir «esto lo oimos
     * nosotros» o «esto lo oyo la red de AISHub». */
    (LIVEAL.src ? '<span class="la-src">' + esc(LIVEAL.src) + '</span>' : '');
  } else {
    el.className = 'note la-off';
    el.textContent = t('la_off');
  }
}
