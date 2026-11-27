/* live.js - true LIVE mode and the georeferenced SAR layer.
 *
 * Two facts verified before writing this:
 *   - meri.digitraffic.fi answers with `access-control-allow-origin: *`, so the
 *     browser can poll it directly. No proxy, no key.
 *   - Microsoft Planetary Computer signs Sentinel-1 GRD with an ANONYMOUS SAS
 *     token and exposes a tilejson endpoint, so SAR can be drawn
 *     georeferenced instead of as a loose quicklook. Verified: HTTP 206 on a
 *     range request against the signed blob.
 *
 * Both are optional: switch them off and the viewer is fully local again. */
'use strict';

/* `at`     cuando contestó la API; `newest` la marca de tiempo del fix más
 *          reciente que trajo. No son lo mismo y el operador necesita el
 *          segundo: es la antigüedad real de lo que está mirando.
 * `follow` mientras esté activo, cada sondeo arrastra el cursor al presente.
 *          Mover el cursor a mano lo desactiva sin apagar el modo en vivo. */
var LIVE = { on: false, timer: null, layer: null, at: 0, newest: 0, n: 0,
             err: null, follow: true, winRef: null, last: [] };
var AIS_URL = 'https://meri.digitraffic.fi/api/ais/v1/locations';
var SARLAYER = null;

function liveFetch() {
  return fetch(AIS_URL, { headers: { 'Digitraffic-User': 'custody-mvp/0.1' } })
    .then(function (r) {
      if (!r.ok) { throw new Error('HTTP ' + r.status); }
      return r.json();
    })
    .then(function (fc) {
      var feats = (fc.features || []).filter(function (f) {
        var c = f.geometry && f.geometry.coordinates;
        return c && c[1] >= AOI[0][0] && c[1] <= AOI[1][0] &&
                    c[0] >= AOI[0][1] && c[0] <= AOI[1][1];
      });
      LIVE.at = Date.now(); LIVE.n = feats.length; LIVE.err = null;
      LIVE.last = feats;
      drawLive(feats);
      /* El dato en vivo tambien alimenta el historial en memoria, asi que la
       * linea temporal crece mientras la pestana esta abierta. */
      feats.forEach(function (f) {
        var p = f.properties, m = String(p.mmsi);
        var t = p.timestampExternal;
        if (!t) { return; }
        if (t > LIVE.newest) { LIVE.newest = t; }
        if (!HIST[m]) { HIST[m] = { name: p.name || null, ship_type: null, pts: [] }; }
        var pts = HIST[m].pts;
        if (!pts.length || pts[pts.length - 1].t < t) {
          pts.push({ t: t, lon: f.geometry.coordinates[0],
                     lat: f.geometry.coordinates[1], sog: p.sog });
        }
      });
      liveAdvanceTime();
      return feats.length;
    })
    .catch(function (e) { LIVE.err = e.message; drawLive([]); throw e; });
}

/* El modo en vivo ES cobertura: mientras sondeamos cada 60 s hay dato nuevo,
 * y la línea de tiempo tiene que reflejarlo o el cursor se queda clavado en
 * el final del build mientras los barcos se mueven en el mapa. */
function liveAdvanceTime() {
  if (typeof TIME === 'undefined' || !LIVE.newest) { return; }
  TIME.now = Date.now();
  if (LIVE.newest > TIME.t1) { TIME.t1 = LIVE.newest; }
  if (!LIVE.winRef) {
    LIVE.winRef = [LIVE.newest, LIVE.newest];
    TIME.win.push(LIVE.winRef);
  } else {
    LIVE.winRef[1] = Math.max(LIVE.winRef[1], LIVE.newest);
  }
  applyView();
  if (LIVE.follow) { setCursor(TIME.t1, false, true); }
  else { renderTimeBar(); }
}

/* El modo en vivo YA NO PINTA una capa propia.
 *
 * Es el mismo dato: liveFetch mete cada fix en HIST, que es exactamente lo
 * que lee la instantanea del cursor. Dibujarlo aparte era pintar dos veces el
 * ultimo punto de la misma linea temporal, con otro color, y encima dejaba
 * dos controles para lo mismo.
 *
 * Lo que hace ahora en vivo: traer dato cada 60 s y empujar el cursor al
 * instante mas nuevo. Lo que se ve lo decide el cursor, siempre.
 */
function drawLive() {
  if (LIVE.layer) { map.removeLayer(LIVE.layer); LIVE.layer = null; }
  delete layers.live;
}

function liveOn() {
  if (LIVE.on) { return Promise.resolve(); }
  LIVE.on = true;
  LIVE.follow = true;
  stopPlay();
  if (snapLayer) { map.removeLayer(snapLayer); snapLayer = null; }
  if (layers.positions && map.hasLayer(layers.positions)) { map.removeLayer(layers.positions); }
  /* La ventana por defecto es «todo», que con días de hueco deja el cursor
   * perdido en el pasado. Al entrar en vivo lo que importa son las últimas
   * horas, así que se encuadra ahí salvo que ya hubiera un encuadre más
   * estrecho elegido a mano. */
  if (TIME.viewMs === null || TIME.viewMs > 6 * 3600e3) { TIME.viewMs = 6 * 3600e3; }
  renderTimeBar();
  var tick = function () {
    liveFetch().catch(function () { renderTimeBar(); });
  };
  tick();
  LIVE.timer = setInterval(tick, 60000);
  return Promise.resolve();
}

function liveOff() {
  LIVE.on = false;
  delete layers.live;
  LIVE.follow = true;
  if (LIVE.timer) { clearInterval(LIVE.timer); LIVE.timer = null; }
  if (LIVE.layer) { map.removeLayer(LIVE.layer); LIVE.layer = null; }
  renderTimeBar();
}

/* El SAR y el optico los gestiona imagery.js, que es comun a los dos y ata
 * la imagen al cursor temporal. Aqui solo queda el AIS en vivo. */
function initSarControl() { if (window.initImagery) { initImagery(); } }
