/* lazy.js - descarga bajo demanda, en segundo plano, con progreso.
 *
 * Los ficheros grandes dejan de bloquear el arranque: se piden cuando se
 * enciende su capa, o en segundo plano cuando el resto ya esta pintado.
 * El progreso se lee de Content-Length cuando el servidor lo manda; si no,
 * se muestra lo descargado sin porcentaje, que es honesto y sigue informando. */
'use strict';

var LAZY = {};   /* file -> {state, pct, bytes, total, layer} */

function fetchWithProgress(url, onProgress) {
  return fetch(url).then(function (r) {
    if (!r.ok) { throw new Error(url + ' -> HTTP ' + r.status); }
    var total = +(r.headers.get('content-length') || 0);
    if (!r.body || !window.ReadableStream) { return r.json(); }   /* sin stream: igual funciona */
    var got = 0, chunks = [];
    var reader = r.body.getReader();
    var pump = function () {
      return reader.read().then(function (res) {
        if (res.done) {
          var buf = new Uint8Array(got), off = 0;
          chunks.forEach(function (c) { buf.set(c, off); off += c.length; });
          return JSON.parse(new TextDecoder().decode(buf));
        }
        chunks.push(res.value); got += res.value.length;
        if (onProgress) { onProgress(got, total); }
        return pump();
      });
    };
    return pump();
  });
}

function lazyLoad(key, file, builder) {
  if (LAZY[key] && LAZY[key].state === 'done') { return Promise.resolve(LAZY[key].layer); }
  if (LAZY[key] && LAZY[key].promise) { return LAZY[key].promise; }
  LAZY[key] = { state: 'loading', pct: 0, bytes: 0, total: 0 };
  renderLazyBar();
  var pr = fetchWithProgress('data/' + file, function (got, total) {
    LAZY[key].bytes = got; LAZY[key].total = total;
    LAZY[key].pct = total ? Math.round(100 * got / total) : 0;
    renderLazyBar();
  }).then(function (fc) {
    LAZY[key].state = 'done'; LAZY[key].pct = 100;
    builder(fc);
    LAZY[key].layer = layers[key];
    renderLazyBar(); renderLayers();
    return layers[key];
  }).catch(function (e) {
    LAZY[key].state = 'failed'; LAZY[key].error = e.message;
    renderLazyBar();
  });
  LAZY[key].promise = pr;
  return pr;
}

function renderLazyBar() {
  var el = document.getElementById('lazybar');
  if (!el) { return; }
  var busy = Object.keys(LAZY).filter(function (k) { return LAZY[k].state === 'loading'; });
  if (!busy.length) { el.hidden = true; el.innerHTML = ''; return; }
  el.hidden = false;
  el.innerHTML = busy.map(function (k) {
    var L_ = LAZY[k];
    var kb = Math.round(L_.bytes / 1024);
    var txt = L_.total ? (L_.pct + '%') : (kb + ' kB');
    return '<div class="lz"><span class="lz-n">' + esc(layerName(k)) + '</span>' +
      '<span class="lz-b"><i style="width:' + (L_.total ? L_.pct : 40) + '%"></i></span>' +
      '<span class="lz-p">' + txt + '</span></div>';
  }).join('');
}

/* Precarga en segundo plano, de menor a mayor, cuando el mapa ya es usable.
 * requestIdleCallback si existe; si no, un timeout corto. */
function prefetchIdle(jobs) {
  var run = function () {
    var job = jobs.shift();
    if (!job) { return; }
    job().then(function () {
      if (window.requestIdleCallback) { requestIdleCallback(run, { timeout: 4000 }); }
      else { setTimeout(run, 400); }
    });
  };
  if (window.requestIdleCallback) { requestIdleCallback(run, { timeout: 4000 }); }
  else { setTimeout(run, 1200); }
}
