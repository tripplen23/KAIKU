/* imagery.js - capas de imagen satelital bajo demanda, atadas al tiempo.
 *
 * Tres cosas que conviene entender antes de leer el codigo:
 *
 * 1. NO SE DESCARGAN GIGAS. Un producto Sentinel-2 completo pesa ~1 GB, pero
 *    aqui no se descarga el producto: se piden TESELAS de 256x256 al servicio
 *    de Planetary Computer, que corta el raster en el servidor. Solo viajan
 *    las teselas del area y el zoom que estas mirando, unos 10-30 kB cada una.
 *    Esa es la segmentacion espacial, y es gratis y anonima.
 *
 * 2. EL CATALOGO SE PIDE POR VISTA. La busqueda STAC se acota al bbox actual
 *    y a una ventana temporal, asi que la respuesta son kilobytes de metadatos,
 *    no el archivo entero.
 *
 * 3. EL TIEMPO ES EL PRODUCTO. Cada escena tiene fecha de adquisicion. En modo
 *    "seguir al cursor", la imagen cambia a la escena mas proxima al instante
 *    del cursor temporal, de modo que mover la linea de tiempo reproduce el
 *    estado del mundo: barcos y fondo avanzan juntos. */
'use strict';

var PC_STAC = 'https://planetarycomputer.microsoft.com/api/stac/v1/search';
var PC_TJ = 'https://planetarycomputer.microsoft.com/api/data/v1/item/tilejson.json';

/* Todo lo de Planetary Computer pasa por el proxy con cache en disco de
 * server.py. Los pixeles de una escena ya adquirida no cambian nunca, asi que
 * la segunda vez que mires la misma zona no hay red de por medio. Si el visor
 * se sirve con `python3 -m http.server` el proxy no existe: se detecta a la
 * primera y se cae a la conexion directa, que funciona igual pero lenta. */
var PROXY = { on: null };       /* null = sin comprobar */

function proxyProbe() {
  if (PROXY.on !== null) { return Promise.resolve(PROXY.on); }
  return fetch('/cache/stats').then(function (r) {
    PROXY.on = r.ok; return PROXY.on;
  }).catch(function () { PROXY.on = false; return false; });
}

function pcStacUrl() {
  return PROXY.on ? '/cache/stac?u=' + encodeURIComponent(PC_STAC) : PC_STAC;
}
function pcMetaUrl(u) {
  return PROXY.on ? '/cache/meta?u=' + encodeURIComponent(u) : u;
}
function pcTileUrl(tpl) {
  /* La plantilla va codificada en la query, asi que sus propios {z}/{x}/{y}
   * quedan como %7Bz%7D y Leaflet no los toca: solo sustituye los de la ruta,
   * que es exactamente lo que queremos. */
  return PROXY.on
    ? '/cache/tile/{z}/{x}/{y}?tpl=' + encodeURIComponent(tpl)
    : tpl;
}

var IMAGERY = {
  /* EL RADAR VIENE ENCENDIDO, Y EN MODO MOSAICO.
   *
   * Es la capa que contesta la pregunta del producto -- que hay en el mar que
   * el AIS no cuenta -- asi que arrancar con ella apagada obliga a tres clics
   * antes de ver nada. `follow: false` es lo que la pone en mosaico: cobertura
   * mas reciente en todas partes, en vez de una escena en un instante.
   * Sentinel-2 sigue apagado: el optico no sirve de noche ni con nube, que
   * por encima de 60 N es la mayor parte del anyo. */
  s1: { id: 's1', coll: 'sentinel-1-grd', assets: 'vv', extra: '&rescale=0,500&tile_format=png',
        label: 'Sentinel-1 SAR', on: true, scenes: [], layers: {}, follow: false, maxAgeDays: 30 },
  s2: { id: 's2', coll: 'sentinel-2-l2a', assets: 'visual', extra: '',
        label: 'Sentinel-2 optical', on: false, scenes: [], layers: {}, follow: true,
        maxAgeDays: 45, cloudLt: 40 }
};
/* id -> {pending, done, errors, aborted, lastMs, stalled}
 *
 * BUG QUE ESTO ARREGLA: se contaba `tileloadstart` contra `tileload` +
 * `tileerror`. Falta un tercer final. Cuando desplazas o haces zoom antes de
 * que una tesela termine, Leaflet CANCELA la petición y emite `tileabort`,
 * que no es ni carga ni error: el contador `pending` se quedaba por encima de
 * `done` para siempre y la barra se congelaba a media altura — el 80 % que no
 * avanzaba nunca. Y como los contadores eran acumulativos y no se reiniciaban
 * entre refrescos, el porcentaje dejaba de significar nada tras unos zooms.
 *
 * Además hay un caso que ningún contador puede resolver: que el servidor
 * simplemente no conteste. Para eso está el vigilante de `lastMs`: si nada se
 * mueve durante IMG_STALL_MS, se dice que está atascado en vez de fingir que
 * sigue cargando. */
var IMG_PROGRESS = {};
var IMG_STALL_MS = 15000;
var _imgStallTimer = null;

function imgCursorMs() {
  if (typeof TIME !== 'undefined' && TIME.cursor !== null && TIME.cursor !== undefined) {
    return TIME.cursor;
  }
  if (typeof TIME !== 'undefined' && TIME.t1) { return TIME.t1; }
  return Date.now();
}

function viewAreaKm2() {
  var b = map.getBounds();
  var lat = (b.getNorth() + b.getSouth()) / 2;
  return Math.abs(b.getEast() - b.getWest()) * 111.32 * Math.cos(lat * Math.PI / 180)
       * Math.abs(b.getNorth() - b.getSouth()) * 111.32;
}

/* -------------------------------------------------- catalogo por vista */
function imgSearch(cfg) {
  var b = map.getBounds();
  /* Cuantizar bbox y tiempo para que dos encuadres vecinos acierten en la
   * cache de disco (/cache/stac) en vez de fallar el 100 % de las veces. */
  var snap = 0.5;
  var qbox = [
    Math.floor(b.getWest() / snap) * snap,
    Math.floor(b.getSouth() / snap) * snap,
    Math.ceil(b.getEast() / snap) * snap,
    Math.ceil(b.getNorth() / snap) * snap
  ];
  var at = Math.round(imgCursorMs() / 3600e3) * 3600e3;
  var half = (cfg.follow ? cfg.maxAgeDays : cfg.maxAgeDays * 3) * 86400e3;
  var body = {
    collections: [cfg.coll],
    bbox: qbox,
    datetime: new Date(at - half).toISOString() + '/' + new Date(at + half).toISOString(),
    /* Cuantas escenas hacen falta depende del tamanyo de la vista: una franja
     * Sentinel-1 cubre ~250 km, asi que el Baltico entero necesita cientos.
     * Medido: con 250 el catalogo solo abarcaba 3 dias y cubria el 79 % de la
     * vista; Planetary Computer admite 1000, que son ~25 dias y cobertura
     * completa. El `fields` mantiene la respuesta en kilobytes y el proxy la
     * cachea, asi que pedir de mas no cuesta red en el segundo intento. */
    limit: Math.max(40, Math.min(1000, Math.round(viewAreaKm2() / 3000))),
    /* Extension `fields`: pedir solo lo que usamos. La geometria entra porque
     * el bbox recto de una franja inclinada no sirve para saber si cubre un
     * punto: eso es lo que dejaba huecos negros en el mosaico. */
    fields: { include: ['id', 'bbox', 'geometry', 'properties.datetime',
                        'properties.eo:cloud_cover'],
              exclude: ['assets', 'links', 'stac_extensions'] }
  };
  if (cfg.cloudLt) { body.query = { 'eo:cloud_cover': { lt: cfg.cloudLt } }; }
  return fetch(pcStacUrl(), { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      cfg.scenes = (d.features || []).map(function (f) {
        return { id: f.id, t: Date.parse(f.properties.datetime),
                 cloud: f.properties['eo:cloud_cover'],
                 bbox: f.bbox, geom: f.geometry,
                 bounds: L.latLngBounds([f.bbox[1], f.bbox[0]], [f.bbox[3], f.bbox[2]]) };
      });
      return cfg.scenes;
    });
}

/* Para cada zona de la vista, la escena mas proxima en el tiempo al cursor.
 * Se eligen hasta 6 para no saturar: cubren el encuadre tipico del golfo. */
/* Dos modos, y la diferencia importa:
 *
 *   follow = true  -> RECONSTRUCCION. Manda el instante: se eligen las escenas
 *                     mas proximas al cursor aunque dejen huecos. Lo que ves es
 *                     lo que el satelite vio ENTONCES, y los huecos son reales.
 *
 *   follow = false -> COBERTURA. Manda el area: se rellena toda la vista con la
 *                     mejor escena disponible de cada zona, aunque sean de
 *                     fechas distintas. Es un mosaico compuesto, no un instante.
 *
 * El modo cobertura usa una rejilla 4x4 sobre la vista y, para cada celda sin
 * cubrir, elige la escena que la toca con mejor calidad: menos nube en optico,
 * mas reciente en radar. */
function imgPick(cfg) {
  var view = map.getBounds();
  var hits = cfg.scenes.filter(function (s) { return s.bounds.intersects(view); });
  if (!hits.length) { return []; }

  if (cfg.follow) {
    var at = imgCursorMs();
    hits.sort(function (a, b) { return Math.abs(a.t - at) - Math.abs(b.t - at); });
    var out = [], covered = [];
    hits.forEach(function (s) {
      if (out.length >= 6) { return; }
      if (covered.some(function (c) { return c.contains(s.bounds); })) { return; }
      out.push(s); covered.push(s.bounds);
    });
    return out;
  }

  /* modo cobertura: rellenar la vista entera, sin huecos.
   *
   * Lo anterior usaba una rejilla fija de 4x4 y un tope de 10 escenas. Al
   * alejarse para ver el Baltico eso dejaba la mayor parte del mapa en negro,
   * que es justo lo contrario de poner en valor el catalogo de la ESA: la
   * cobertura Sentinel-1 del Baltico es practicamente total y hay que verlo.
   *
   * Ahora la rejilla se escala con el tamanyo de la vista y, para cada celda
   * sin cubrir, se elige la MEJOR escena que la contenga de verdad -- por
   * huella, no por bbox. Para radar, mejor = mas reciente; para optico, menos
   * nube. Las escenas se dibujan de mas vieja a mas nueva, asi que lo
   * reciente queda encima. */
  var quality = function (s) {
    if (cfg.cloudLt !== undefined && s.cloud !== undefined && s.cloud !== null) {
      return s.cloud;                 /* optico: menos nube es mejor */
    }
    return -(s.t / 1e9);              /* radar: mas reciente es mejor */
  };
  hits.sort(function (a, b) { return quality(a) - quality(b); });

  /* La rejilla decide DONDE se busca escena. Si la celda es grande, un hueco
   * mas pequenyo que ella no se detecta y queda negro: medido, con celdas de
   * ~90 km la cobertura se quedaba en el 89 %. Se afina hasta celdas de ~45 km,
   * que es bastante menor que el ancho de franja de Sentinel-1. */
  var km = Math.sqrt(viewAreaKm2());
  var N = Math.max(4, Math.min(28, Math.round(km / 45)));
  var out2 = [];
  var sw = view.getSouthWest(), ne = view.getNorthEast();
  var dLat = (ne.lat - sw.lat) / N, dLon = (ne.lng - sw.lng) / N;
  for (var i = 0; i < N; i += 1) {
    for (var jj = 0; jj < N; jj += 1) {
      var clat = sw.lat + (i + 0.5) * dLat, clon = sw.lng + (jj + 0.5) * dLon;
      var covered = out2.some(function (s) {
        var g = geomContains(s.geom, clon, clat);
        return g === null ? s.bounds.contains(L.latLng(clat, clon)) : g;
      });
      if (covered) { continue; }
      for (var k = 0; k < hits.length; k += 1) {
        var g2 = geomContains(hits[k].geom, clon, clat);
        var inside = g2 === null
          ? hits[k].bounds.contains(L.latLng(clat, clon)) : g2;
        if (inside && out2.indexOf(hits[k]) < 0) { out2.push(hits[k]); break; }
      }
    }
  }
  /* Mas vieja primero: al anyadirse al mapa en ese orden, la mas reciente
   * queda arriba y es la que se ve donde se solapan. */
  out2.sort(function (a, b) { return a.t - b.t; });
  return out2;
}

/* ------------------------------------------------------ carga de teselas */
function imgAddScene(cfg, sc) {
  var key = cfg.id + '|' + sc.id;
  if (cfg.layers[key]) { return Promise.resolve(); }
  cfg.layers[key] = 'pending';
  var url = PC_TJ + '?collection=' + cfg.coll + '&item=' + encodeURIComponent(sc.id) +
            '&assets=' + cfg.assets + cfg.extra;
  return fetch(pcMetaUrl(url)).then(function (r) { return r.json(); }).then(function (tj) {
    if (!tj.tiles || !tj.tiles.length) { throw new Error('no tiles'); }
    var bb = tj.bounds
      ? L.latLngBounds([tj.bounds[1], tj.bounds[0]], [tj.bounds[3], tj.bounds[2]])
      : sc.bounds;
    var lyr = L.tileLayer(pcTileUrl(tj.tiles[0]), {
      _t: sc.t,                       /* para el apilado por fecha */
      opacity: cfg.id === 's2' ? 0.95 : 0.85, maxZoom: 15, bounds: bb, crossOrigin: true,
      /* Tres anillos de teselas alrededor de la vista. Con cache en disco
       * cuestan poco y eliminan el parpadeo al desplazar. */
      keepBuffer: 3, updateWhenZooming: false, updateWhenIdle: true,
      attribution: cfg.label + ' via Microsoft Planetary Computer · ' +
                   'Contains modified Copernicus Sentinel data'
    });
    /* Progreso real: Leaflet avisa por tesela. Los TRES finales posibles
     * cuentan como terminada, incluido el aborto. */
    var pg = imgProgressFor(cfg.id);
    lyr.on('tileloadstart', function () { pg.pending += 1; imgTick(pg); });
    lyr.on('tileload', function () { pg.done += 1; imgTick(pg); });
    /* Aqui NO se reregistra nada: esto es una capa POR ESCENA, con su propia
     * URL de activo, y no depende de ningun mosaico. Lo de reregistrar vive
     * en mosaicApply, que es quien usa el id temporal. */
    lyr.on('tileerror', function () { pg.errors += 1; pg.done += 1; imgTick(pg); });
    lyr.on('tileabort', function () { pg.aborted += 1; pg.done += 1; imgTick(pg); });
    cfg.layers[key] = lyr;
    if (cfg.on) { lyr.addTo(map); }
  }).catch(function () { cfg.layers[key] = 'failed'; });
}

/* ========================================================= mosaico servidor */
/* El mosaico a mano no escalaba: 165 capas de teselas para cubrir el Baltico,
 * con costuras visibles entre escenas y la pagina arrastrandose. La solucion
 * clasica para esto no es dibujar N capas sino registrar una BUSQUEDA y dejar
 * que el servidor componga: es lo que hace titiler-pgstac, y Planetary
 * Computer lo expone.
 *
 *   POST /api/data/v1/mosaic/register   {collections, bbox, datetime, sortby}
 *     -> {id}
 *   GET  /api/data/v1/mosaic/{id}/tilejson.json?assets=vv&rescale=..
 *     -> plantilla de teselas
 *
 * `sortby: datetime desc` es lo que hace que, donde dos pasadas se solapan,
 * gane la mas reciente. Eso antes lo hacia nuestro apilado por z-index con N
 * capas; ahora lo resuelve el servidor en un pixel.
 *
 * UNA capa en vez de 165, sin costuras de opacidad y sin 165 juegos de
 * peticiones.
 *
 * LIMITE COMPROBADO (2026-11-11): minzoom 8. Por debajo las teselas vuelven
 * vacias -- es la proteccion de titiler-pgstac contra barrer miles de assets
 * de golpe. No se disimula: por debajo de z8 no se pinta radar y se dice por
 * que. A esa escala un pixel de 10 m reducido a 1 km es ruido de todos modos.
 */
var MOSAIC_MINZOOM = 8;
var MOSAIC_REG = 'https://planetarycomputer.microsoft.com/api/data/v1/mosaic/register';
var MOSAIC_BASE = 'https://planetarycomputer.microsoft.com/api/data/v1/mosaic/';

function mosaicKey(cfg, win) {
  return cfg.id + '|' + win[0] + '|' + win[1];
}

/* CUANTO VALE UN REGISTRO DE MOSAICO ANTES DE REHACERLO.
 *
 * Planetary Computer no devuelve datos al registrar: devuelve el
 * IDENTIFICADOR de un recurso que crea en su lado y que CADUCA. Cuando
 * caduca, todas las teselas contestan 410 Gone y el radar desaparece del mapa
 * sin que nada diga por que -- medido el 2026-11-13, 58 % de las teselas en
 * 410 con un id de tres horas.
 *
 * Veinte minutos es un techo prudente, no una vida medida: PC no documenta
 * cuanto duran. El techo es el cinturon; los tirantes son reregistrar en
 * cuanto las teselas empiezan a fallar (ver mosaicStale). */
var MOSAIC_TTL_MS = 20 * 60 * 1000;

/* Un registro caducado se nota por el PATRON de fallos, no por una tesela
 * suelta: sobre mar sin pasada reciente una tesela puede fallar y es normal.
 * Si falla la mayoria de un lote entero, es que el id ya no existe. */
function mosaicStale(cfg) {
  var pg = imgProgressFor(cfg.id);
  return pg.done >= 8 && pg.errors / pg.done > 0.5;
}

function mosaicForget(cfg) {
  cfg._mosaic = null;
  cfg._mlayerTpl = null;
}

/* Registra la busqueda y devuelve la plantilla de teselas. Se cachea por
 * ventana temporal: mover el mapa no vuelve a registrar nada, solo pedir
 * teselas distintas de la misma busqueda. */
function mosaicTemplate(cfg) {
  var at = imgCursorMs();
  var half = cfg.maxAgeDays * 86400e3;
  /* Se redondea a dia para que pequenyos movimientos del cursor no generen
   * un registro nuevo por cada pixel arrastrado. */
  var d = 86400e3;
  var win = [Math.floor((at - half) / d) * d, Math.ceil((at + d) / d) * d];
  var key = mosaicKey(cfg, win);
  if (cfg._mosaic && cfg._mosaic.key === key &&
      Date.now() - cfg._mosaic.at < MOSAIC_TTL_MS) {
    return Promise.resolve(cfg._mosaic.tpl);
  }
  var body = {
    collections: [cfg.coll],
    datetime: new Date(win[0]).toISOString() + '/' + new Date(win[1]).toISOString(),
    /* Lo mas reciente manda donde se solapan las pasadas. */
    sortby: [{ field: 'datetime', direction: 'desc' }]
  };
  if (cfg.cloudLt) { body.query = { 'eo:cloud_cover': { lt: cfg.cloudLt } }; }
  var regUrl = (window.PROXY && PROXY.on)
    ? '/cache/stac?u=' + encodeURIComponent(MOSAIC_REG) : MOSAIC_REG;
  return fetch(regUrl, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    .then(function (r) { return r.json(); })
    .then(function (d2) {
      if (!d2 || !d2.id) { throw new Error('mosaic register: sin id'); }
      var tjUrl = MOSAIC_BASE + d2.id + '/tilejson.json?assets=' + cfg.assets +
                  cfg.extra;
      return fetch(pcMetaUrl(tjUrl)).then(function (r) { return r.json(); });
    })
    .then(function (tj) {
      if (!tj || !tj.tiles || !tj.tiles.length) { throw new Error('mosaic: sin tiles'); }
      /* El servidor exige `collection` en la peticion de tesela aunque ya
       * este en la busqueda registrada. Comprobado: sin el, 422. */
      var tpl = tj.tiles[0] +
        (tj.tiles[0].indexOf('collection=') < 0 ? '&collection=' + cfg.coll : '');
      cfg._mosaic = { key: key, tpl: tpl, at: Date.now() };
      return tpl;
    });
}

/* Por debajo de este zoom se suelta el mosaico, y el numero esta MEDIDO.
 *
 * El tiler de Planetary Computer no renderiza mosaicos por debajo de z8: de
 * z3 a z7 contesta 204 sin contenido, diga lo que diga el `minzoom` del
 * tilejson (comprobado el 2026-11-13; declara 0 y no sirve nada). Asi que por
 * debajo de z8 Leaflet pide teselas de z8 y las reescala, y cada nivel que se
 * aleja cuadruplica cuantas hacen falta para llenar la vista:
 *
 *     zoom   teselas    resultado
 *      7       96       completo
 *      6      168       completo, ~40 s
 *      5      241       28 % a los 60 s: un tablero de ajedrez
 *
 * A z5 no falla, pero tarda tanto que la primera impresion es un mosaico
 * roto. Por eso el suelo es 6 y no 5, y por eso la capa AVISA en el mapa en
 * vez de quedarse en negro: ver imgZoomHint(). */
var MOSAIC_DROP_BELOW = 7;

/* UNA CAPA ENCENDIDA QUE NO PINTA TIENE QUE DECIRLO DONDE SE MIRA.
 *
 * El radar viene encendido de serie y la vista de apertura es z5, un nivel por
 * debajo del suelo. Sin esto el usuario ve la casilla marcada y el mar vacio,
 * y la explicacion esta enterrada en la pestana de capas -- que es justo el
 * fallo que se reporto: «no se estan mostrando las imagenes SAR para nada».
 */
function imgZoomHint() {
  var waiting = Object.keys(IMAGERY).filter(function (k) {
    return IMAGERY[k].on && !IMAGERY[k].follow;
  });
  if (!waiting.length || map.getZoom() >= MOSAIC_DROP_BELOW) {
    /* La condicion ya no se da: fuera el aviso. Solo el pegajoso, para no
     * tragarse un destello de otra cosa. */
    if (window.clearMapNote) { clearMapNote(true); }
    return;
  }
  if (window.flashMapNote) {
    flashMapNote(t('mos_hint', { z: MOSAIC_DROP_BELOW,
                                n: waiting.map(function (k) { return IMAGERY[k].label; })
                                          .join(' + ') }), true);
  }
}

function mosaicApply(cfg) {
  if (map.getZoom() < MOSAIC_DROP_BELOW) {
    mosaicRemove(cfg);
    imgRenderStatus(cfg, []);
    imgZoomHint();
    return Promise.resolve();
  }
  return mosaicTemplate(cfg).then(function (tpl) {
    if (!cfg.on) { return; }
    if (cfg._mlayer && cfg._mlayerTpl === tpl) { return; }
    mosaicRemove(cfg);
    var lyr = L.tileLayer(pcTileUrl(tpl), {
      opacity: cfg.id === 's2' ? 0.95 : 0.85,
      /* minNativeZoom, NO minZoom. `minZoom` en una capa se lo impone al mapa
       * entero y desactiva el boton de alejar; `minNativeZoom` solo dice
       * hasta donde hay teselas y deja que Leaflet reescale las de z8 al
       * alejarse, que es justo lo que se quiere: no quedarse en negro. */
      minNativeZoom: MOSAIC_MINZOOM, maxZoom: 15, crossOrigin: true,
      keepBuffer: 1, updateWhenZooming: false, updateWhenIdle: true,
      zIndex: cfg.id === 's2' ? 20 : 200,
      attribution: cfg.label + ' mosaic via Microsoft Planetary Computer · ' +
                   'Contains modified Copernicus Sentinel data'
    });
    var pg = imgProgressFor(cfg.id);
    lyr.on('tileloadstart', function () { pg.pending += 1; imgTick(pg); });
    lyr.on('tileload', function () { pg.done += 1; imgTick(pg); });
    lyr.on('tileerror', function () {
      pg.errors += 1; pg.done += 1; imgTick(pg);
      /* Un id caducado hace fallar el lote entero. Se reregistra UNA vez por
       * capa y se vuelve a pintar; sin esto el radar se quedaba en negro
       * hasta recargar la pagina. */
      if (!cfg._reregistered && mosaicStale(cfg)) {
        cfg._reregistered = true;
        mosaicForget(cfg);
        mosaicRemove(cfg);
        imgProgressReset(cfg.id);
        mosaicApply(cfg).then(function () { cfg._reregistered = false; });
      }
    });
    lyr.on('tileabort', function () { pg.aborted += 1; pg.done += 1; imgTick(pg); });
    cfg._mlayer = lyr; cfg._mlayerTpl = tpl;
    lyr.addTo(map);
    layers[cfg.id + '_mosaic'] = lyr;
    imgRenderStatus(cfg, []);
    imgZoomHint();            /* ya pinta: retira el aviso */
  }).catch(function (e) {
    cfg._mosaicErr = String(e.message || e);
    imgRenderStatus(cfg, []);
  });
}

function mosaicRemove(cfg) {
  if (cfg._mlayer) { map.removeLayer(cfg._mlayer); }
  cfg._mlayer = null; cfg._mlayerTpl = null;
  delete layers[cfg.id + '_mosaic'];
}

/* Quita las capas por escena. Al pasar a mosaico sobran todas. */
function sceneLayersRemove(cfg) {
  Object.keys(cfg.layers).forEach(function (k) {
    var lyr = cfg.layers[k];
    if (lyr && typeof lyr !== 'string' && map.hasLayer(lyr)) { map.removeLayer(lyr); }
  });
}


function imgRefresh(cfg) {
  if (!cfg.on) { return Promise.resolve(); }
  /* Cada refresco es una carga nueva: los contadores arrancan de cero o el
   * porcentaje acaba midiendo la historia entera de la sesión. */
  imgProgressReset(cfg.id);

  /* DOS MODOS, DOS MECANISMOS DISTINTOS, y la diferencia no es tecnica:
   *
   *   cobertura (follow=false)  -> MOSAICO. La pregunta es «como esta el mar
   *       ahora, en todas partes». Da igual de que pasada venga cada pixel
   *       mientras sea la mas reciente, asi que lo compone el servidor.
   *
   *   reconstruccion (follow=true) -> UNA ESCENA. La pregunta es «que vio el
   *       satelite en ESTE instante». Un mosaico mezclaria fechas y mentiria
   *       sobre el momento, que es justo lo que no puede pasar aqui. */
  if (!cfg.follow) {
    sceneLayersRemove(cfg);
    /* En modo mosaico el servidor compone las escenas por su cuenta y los
     * carriles/recortes ya leen window.PASSES (loadPassCatalogue): lanzar
     * imgSearch() en cada desplazamiento o zoom solo bloqueaba el hilo y
     * enviaba decenas de busquedas STAC innecesarias. */
    return mosaicApply(cfg);
  }
  mosaicRemove(cfg);
  return imgSearch(cfg).then(function () {
    var want = imgPick(cfg);
    var wantKeys = want.map(function (s) { return cfg.id + '|' + s.id; });
    Object.keys(cfg.layers).forEach(function (k) {
      var lyr = cfg.layers[k];
      if (!lyr || typeof lyr === 'string') { return; }
      if (wantKeys.indexOf(k) < 0 && map.hasLayer(lyr)) { map.removeLayer(lyr); }
    });
    imgRenderStatus(cfg, want);
    return Promise.all(want.map(function (s) { return imgAddScene(cfg, s); }))
      .then(function () { return wantKeys; });
  }).then(function (wantKeys) {
    /* imgPick se llamaba otra vez aqui, por escena. Con 10 escenas eso era
     * diez recorridos del catalogo por refresco, y el refresco ocurre en cada
     * zoom. La lista ya la teniamos calculada. */
    wantKeys.forEach(function (k) {
      var lyr = cfg.layers[k];
      if (lyr && typeof lyr !== 'string' && !map.hasLayer(lyr)) { lyr.addTo(map); }
    });
    restackImagery();
  });
}

/* Apilado explicito por fecha. `bringToBack` dejaba la ULTIMA escena anyadida
 * al fondo, que es justo lo contrario de lo que se quiere: donde dos pasadas
 * se solapan tiene que verse la mas reciente. Y como imgAddScene resuelve de
 * forma asincrona, el orden de llegada no es el cronologico: con z-index
 * explicito da igual en que orden lleguen.
 *
 * Los rangos dejan el optico por debajo del radar: el radar es el que ve de
 * noche y con nube, que es la mayor parte del anyo por encima de 60N. */
function restackImagery() {
  var base = { s2: 20, s1: 200 };
  Object.keys(IMAGERY).forEach(function (k) {
    var cfg = IMAGERY[k];
    if (!cfg || !cfg.layers) { return; }
    var live = Object.keys(cfg.layers)
      .map(function (key) { return { key: key, lyr: cfg.layers[key] }; })
      .filter(function (x) { return x.lyr && typeof x.lyr !== 'string'; });
    /* Mas vieja = z menor. La mas reciente queda arriba del todo. */
    live.sort(function (a, b) {
      var ta = (a.lyr.options && a.lyr.options._t) || 0;
      var tb = (b.lyr.options && b.lyr.options._t) || 0;
      return ta - tb;
    });
    live.forEach(function (x, i) {
      if (x.lyr.setZIndex) { x.lyr.setZIndex((base[k] || 100) + i); }
    });
  });
}

function imgSyncSources() {
  if (window.renderSources) { renderSources(); renderSourceStrip(); }
}

function imgOn(cfg) {
  cfg.on = true;
  imgSyncSources();
  if (!IMAGERY._bound) {
    /* Sin freno, arrastrar el mapa encadena una busqueda STAC por cada
     * `moveend` y el visor se atasca persiguiendose a si mismo. */
    map.on('moveend zoomend', function () {
      if (IMAGERY._deb) { clearTimeout(IMAGERY._deb); }
      IMAGERY._deb = setTimeout(function () {
        Object.keys(IMAGERY).forEach(function (k) {
          if (IMAGERY[k] && IMAGERY[k].on) { imgRefresh(IMAGERY[k]); } });
      }, 350);
    });
    IMAGERY._bound = true;
  }
  return proxyProbe().then(function () { return imgRefresh(cfg); });
}
function imgOff(cfg) {
  cfg.on = false;
  imgSyncSources();
  mosaicRemove(cfg);
  Object.keys(cfg.layers).forEach(function (k) {
    var lyr = cfg.layers[k];
    if (lyr && typeof lyr !== 'string' && map.hasLayer(lyr)) { map.removeLayer(lyr); }
  });
  delete IMG_PROGRESS[cfg.id];
  imgRenderProgress(); imgRenderStatus(cfg, []);
}

/* Llamado por la linea de tiempo: la imagen sigue al cursor. */
function imageryFollowCursor() {
  Object.keys(IMAGERY).forEach(function (k) {
    var cfg = IMAGERY[k];
    if (cfg && cfg.on && cfg.follow) { imgRefresh(cfg); }
  });
}

/* ------------------------------------------------------------- interfaz */
function imgProgressFor(id) {
  if (!IMG_PROGRESS[id]) {
    IMG_PROGRESS[id] = { pending: 0, done: 0, errors: 0, aborted: 0,
                         lastMs: Date.now(), stalled: false };
  }
  return IMG_PROGRESS[id];
}
function imgProgressReset(id) {
  IMG_PROGRESS[id] = { pending: 0, done: 0, errors: 0, aborted: 0,
                       lastMs: Date.now(), stalled: false };
}
function imgTick(pg) {
  pg.lastMs = Date.now();
  pg.stalled = false;
  imgRenderProgress();
}

/* Vigilante: mientras haya algo pendiente se comprueba una vez por segundo si
 * el contador se ha movido. Si no, se marca atascado y se dice. Un 80 % que no
 * avanza y no explica nada es peor que un aviso. */
function imgWatch() {
  if (_imgStallTimer) { return; }
  _imgStallTimer = setInterval(function () {
    var live = false, changed = false;
    Object.keys(IMG_PROGRESS).forEach(function (k) {
      var p = IMG_PROGRESS[k];
      if (p.pending <= p.done) { return; }
      live = true;
      var st = (Date.now() - p.lastMs) > IMG_STALL_MS;
      if (st !== p.stalled) { p.stalled = st; changed = true; }
    });
    if (!live) { clearInterval(_imgStallTimer); _imgStallTimer = null; }
    if (changed || !live) { imgRenderProgress(); }
  }, 1000);
}

function imgRenderProgress() {
  var el = document.getElementById('imgprog');
  if (!el) { return; }
  var ids = Object.keys(IMG_PROGRESS).filter(function (k) {
    var p = IMG_PROGRESS[k]; return p.pending > p.done; });
  if (!ids.length) { el.hidden = true; el.innerHTML = ''; return; }
  imgWatch();
  el.hidden = false;
  el.innerHTML = ids.map(function (k) {
    var p = IMG_PROGRESS[k];
    var pct = p.pending ? Math.min(100, Math.round(100 * p.done / p.pending)) : 0;
    var note = '';
    if (p.stalled) {
      note = '<div class="note empty">' + esc(t('img_stalled', {
        n: p.pending - p.done, s: Math.round((Date.now() - p.lastMs) / 1000) })) + '</div>';
    }
    return '<div class="lz' + (p.stalled ? ' stalled' : '') + '">' +
      '<span class="lz-n">' + esc(IMAGERY[k].label) + '</span>' +
      '<span class="lz-b"><i style="width:' + pct + '%"></i></span>' +
      '<span class="lz-p">' + pct + '%</span></div>' + note;
  }).join('') +
  '<div class="btn-row"><button class="btn" id="img-cancel">' +
    esc(t('img_cancel')) + '</button></div>';
  var c = document.getElementById('img-cancel');
  if (c) { c.addEventListener('click', function () {
    /* Parar es apagar las capas de imagen: Leaflet aborta sus peticiones al
     * quitarlas del mapa, y los contadores se van con ellas. */
    Object.keys(IMAGERY).forEach(function (k) {
      if (IMAGERY[k] && IMAGERY[k].on) {
        var cb = document.getElementById(k + '-layer');
        if (cb) { cb.checked = false; }
        imgOff(IMAGERY[k]);
      }
    });
  }); }
}

function imgRenderStatus(cfg, scenes) {
  var el = document.getElementById(cfg.id + '-status');
  if (!el) { return; }
  if (!cfg.on) { el.textContent = ''; return; }
  if (!cfg.follow) {
    /* Modo cobertura: el estado es el del mosaico, no el de N escenas. */
    if (cfg._mosaicErr) {
      el.innerHTML = '<span class="empty">' + esc(cfg._mosaicErr) + '</span>';
    } else if (map.getZoom() < MOSAIC_DROP_BELOW) {
      el.innerHTML = '<span class="empty">' +
        esc(t('mos_zoom', { z: MOSAIC_DROP_BELOW })) + '</span>';
    } else {
      el.innerHTML = esc(t('mos_on'));
    }
    return;
  }
  if (!scenes.length) {
    el.innerHTML = '<span class="empty">' + esc(t('img_none')) + '</span>'; return;
  }
  if (!cfg.follow) {
    var ts = scenes.map(function (s) { return s.t; });
    el.innerHTML = t('img_mosaic', {
      n: scenes.length,
      a: fmtUTC(Math.min.apply(null, ts)).slice(0, 10),
      b: fmtUTC(Math.max.apply(null, ts)).slice(0, 10)
    });
    return;
  }
  var at = imgCursorMs();
  var nearest = scenes.reduce(function (a, b) {
    return Math.abs(a.t - at) < Math.abs(b.t - at) ? a : b; });
  var age = at - nearest.t;
  el.innerHTML = t('img_status', {
    n: scenes.length,
    d: fmtUTC(nearest.t),
    a: (age >= 0 ? '−' : '+') + fmtDur(Math.abs(age))
  }) + (nearest.cloud !== undefined && nearest.cloud !== null
        ? ' · ' + t('img_cloud', { c: Math.round(nearest.cloud) }) : '');
}

function initImagery() {
  ['s1', 's2'].forEach(function (id) {
    var cfg = IMAGERY[id];
    var cb = document.getElementById(id + '-layer');
    if (!cb) { return; }
    cb.addEventListener('change', function () {
      cb.checked ? imgOn(cfg) : imgOff(cfg);
    });
    var fo = document.getElementById(id + '-follow');
    if (fo) {
      fo.checked = cfg.follow;
      fo.addEventListener('change', function () {
        cfg.follow = fo.checked;
        if (cfg.on) { imgRefresh(cfg); }
      });
    }
    /* LA CONFIGURACION MANDA SOBRE EL HTML, y una capa que arranca encendida
     * se ENCIENDE. Antes `on: true` solo pintaba la casilla marcada: nada
     * llamaba a imgOn() al cargar, asi que la capa se quedaba armada y sin
     * activar, y el unico modo de verla era desmarcar y volver a marcar.
     * Es tambien lo que hace aparecer el aviso de zoom al arrancar. */
    cb.checked = !!cfg.on;
    if (cfg.on) {
      cfg.on = false;        // imgOn lo vuelve a poner y hace el resto
      imgOn(cfg);
    }
  });
}

/* ------------------------------------------- catalogo de pasadas para la
 * linea de tiempo. Solo fechas y huellas, con `fields`: unos kB. Sirve para
 * pintar cuando hubo pasada de cada satelite, al lado de cuando grabamos
 * nosotros AIS. */
var PASSES = { s1: [], s2: [], loaded: false };

/* Un bbox permutado a [lat, lon, lat, lon] sigue siendo geometricamente
 * valido: [59, 22, 60.9, 30.5] son coordenadas legales, solo que en el mar de
 * Arabia. Comprobar rangos no basta. Lo que SI distingue un bbox bueno de uno
 * permutado es el dato que ya tenemos: tiene que contener los buques que
 * estamos siguiendo. Si no contiene ninguno, no es nuestra zona. */
function bboxLooksSane(b, positions) {
  if (!b || b.length !== 4) { return false; }
  if (!(Math.abs(b[0]) <= 180 && Math.abs(b[2]) <= 180 &&
        Math.abs(b[1]) <= 90 && Math.abs(b[3]) <= 90 &&
        b[0] < b[2] && b[1] < b[3])) { return false; }
  var pts = positions || knownPositions();
  if (!pts.length) { return true; }          /* sin dato no se puede juzgar */
  return pts.some(function (p) {
    return p[0] >= b[0] && p[0] <= b[2] && p[1] >= b[1] && p[1] <= b[3]; });
}

function knownPositions() {
  var out = [];
  if (typeof HIST === 'undefined') { return out; }
  var keys = Object.keys(HIST);
  for (var i = 0; i < keys.length && out.length < 50; i += 1) {
    var p = HIST[keys[i]].pts;
    if (p && p.length) { out.push([p[p.length - 1].lon, p[p.length - 1].lat]); }
  }
  return out;
}

function loadPassCatalogue(t0, t1, bbox) {
  /* STAC espera [minlon, minlat, maxlon, maxlat] y acepta sin rechistar un
   * bbox permutado, devolviendo escenas de donde no es. Se valida aqui para
   * que el fallo salga por consola en vez de pasar por dato bueno. */
  if (!bboxLooksSane(bbox)) {
    console.error('bbox del catalogo de pasadas no contiene ningun buque conocido; ' +
                  'se espera [minlon, minlat, maxlon, maxlat]', bbox);
    PASSES.s1 = []; PASSES.s2 = []; PASSES.loaded = true;
    return Promise.resolve(PASSES);
  }
  var win = Math.min(t1 - t0, 60 * 86400e3);     /* tope 60 d por peticion */
  var body = function (coll, cloud) {
    var b = { collections: [coll], bbox: bbox,
      datetime: new Date(t1 - win).toISOString() + '/' + new Date(t1).toISOString(),
      limit: 200,
      fields: { include: ['id', 'bbox', 'geometry', 'properties.datetime',
                          'properties.eo:cloud_cover'],
                exclude: ['assets', 'links', 'stac_extensions'] } };
    if (cloud) { b.query = { 'eo:cloud_cover': { lt: cloud } }; }
    return b;
  };
  var get = function (coll, cloud) {
    return fetch(pcStacUrl(), { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body(coll, cloud)) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        return (d.features || []).map(function (f) {
          return { id: f.id, t: Date.parse(f.properties.datetime),
                   cloud: f.properties['eo:cloud_cover'],
                   bbox: f.bbox, geom: f.geometry }; })
          .sort(function (a, b) { return a.t - b.t; });
      }).catch(function () { return []; });
  };
  return proxyProbe().then(function () {
    return Promise.all([get('sentinel-1-grd', null), get('sentinel-2-l2a', null)]);
  })
    .then(function (r) {
      PASSES.s1 = r[0]; PASSES.s2 = r[1]; PASSES.loaded = true;
      if (window.renderTimeBar) { renderTimeBar(); }
      return PASSES;
    });
}

/* El proxy se sondea al cargar, no solo al encender una capa de imagen: las
 * fotos de los buques tambien pasan por el y se piden mucho antes de que
 * nadie toque Sentinel. Va aqui y no en app.js porque imagery.js se carga
 * despues: alli `proxyProbe` todavia no existe y la llamada seria un no-op
 * silencioso, que es peor que un error. */
/* ============================================================== recortes */
/* Un "chip": el trozo de imagen satelital centrado exactamente en un punto y
 * un instante. Es lo que hace Skylight en su panel de eventos, y no hay nada
 * propietario en ello: la miniatura sale del mismo Sentinel-1 publico, por el
 * endpoint `item/bbox` de Planetary Computer, sin cuenta y sin clave.
 * Comprobado el 2026-11-10 contra el punto y la pasada exactos de una captura
 * de Skylight (59.8430, 25.8335, 7-nov-2026 04:41Z, escena
 * S1C_IW_GRDH_1SDV_20261107T044122): devuelve el mismo buque.
 *
 * Para que sirva de prueba y no de adorno, el recorte lleva SIEMPRE:
 *   - el instante de adquisicion y el desfase contra el suceso;
 *   - la escala en metros, porque un buque de 300 m y uno de 30 se parecen
 *     mucho si no hay regla;
 *   - el norte, porque la geometria SAR no es intuitiva;
 *   - el identificador de la escena, para que sea reproducible por un tercero.
 */
var CHIP = { seq: 0, reg: {}, open: {} };
var CHIP_OPEN_KEY = 'custody.chipOpen';

/* Abierto o cerrado, pero NUNCA invisible. La version anterior colapsaba el
 * recorte a una linea sin fondo ni borde cuando no habia nada que enseñar, y
 * desde el punto de vista de quien mira el panel simplemente se evaporaba.
 * Ahora hay una barra siempre, con su motivo escrito, y el estado se recuerda. */
function chipOpen(id) {
  if (CHIP.open[id] !== undefined) { return CHIP.open[id]; }
  try {
    var v = localStorage.getItem(CHIP_OPEN_KEY);
    return v === null ? true : v === '1';
  } catch (e) { return true; }
}
function chipSetOpen(id, v) {
  CHIP.open[id] = !!v;
  try { localStorage.setItem(CHIP_OPEN_KEY, v ? '1' : '0'); } catch (e) {}
  chipRender(id);
}

/* Barra de titulo comun: titulo, estado y el boton de mostrar/ocultar. */
function chipBar(id, st, subtitle) {
  var open = chipOpen(id);
  return '<div class="chip-bar' + (open ? '' : ' closed') + '">' +
    '<button class="chip-toggle" data-chip="' + id + '" data-toggle="1" ' +
      'aria-expanded="' + open + '" title="' + esc(t(open ? 'chip_hide' : 'chip_show')) +
      '"><span class="chev">' + (open ? '&#9662;' : '&#9656;') + '</span>' +
      esc(t('chip_h')) + '</button>' +
    (subtitle ? '<span class="note">' + esc(subtitle) + '</span>' : '') +
    '</div>';
}
var CHIP_SIZES = [250, 500, 1000, 3000];
var CHIP_KIND = {
  s1: { coll: 'sentinel-1-grd', assets: 'vv', extra: '&rescale=0,400',
        label: 'Sentinel-1 SAR (VV)' },
  s2: { coll: 'sentinel-2-l2a', assets: 'visual', extra: '',
        label: 'Sentinel-2 optical' }
};

/* Punto en poligono por lanzamiento de rayo. La huella de una pasada
 * Sentinel-1 es un paralelogramo inclinado; su bbox recto puede ser el doble
 * de grande. Filtrar por bbox devolvia escenas que no cubren el punto y el
 * recorte salia negro. */
function pointInRing(lon, lat, ring) {
  var inside = false;
  for (var i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    var xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
    if (((yi > lat) !== (yj > lat)) &&
        (lon < (xj - xi) * (lat - yi) / ((yj - yi) || 1e-12) + xi)) {
      inside = !inside;
    }
  }
  return inside;
}

function geomContains(g, lon, lat) {
  if (!g) { return null; }                 /* sin geometria no se puede decidir */
  var polys = g.type === 'MultiPolygon' ? g.coordinates
            : (g.type === 'Polygon' ? [g.coordinates] : null);
  if (!polys) { return null; }
  return polys.some(function (poly) {
    if (!pointInRing(lon, lat, poly[0])) { return false; }
    for (var k = 1; k < poly.length; k += 1) {       /* agujeros */
      if (pointInRing(lon, lat, poly[k])) { return false; }
    }
    return true;
  });
}

function passesCovering(kind, lon, lat) {
  var list = (window.PASSES && PASSES[kind]) || [];
  return list.filter(function (p) {
    var b = p.bbox;
    if (b && !(lon >= b[0] && lon <= b[2] && lat >= b[1] && lat <= b[3])) {
      return false;                        /* descarte barato primero */
    }
    var g = geomContains(p.geom, lon, lat);
    return g === null ? true : g;          /* sin geometria, se acepta */
  });
}

function nearestPassIndex(list, tMs) {
  var best = -1, bd = Infinity;
  list.forEach(function (p, i) {
    var d = Math.abs(p.t - tMs);
    if (d < bd) { bd = d; best = i; }
  });
  return best;
}

/* Mismo recorte que la miniatura pero en GeoTIFF: valores reales para que el
 * detector mida contraste en vez de pixeles de PNG ya reescalados. */
function chipTifUrl(kind, pass, lon, lat, metres) {
  var k = CHIP_KIND[kind];
  var dLat = metres / 111320.0;
  var dLon = metres / (111320.0 * Math.cos(lat * Math.PI / 180));
  var bb = [lon - dLon / 2, lat - dLat / 2, lon + dLon / 2, lat + dLat / 2]
    .map(function (x) { return x.toFixed(6); }).join(',');
  return 'https://planetarycomputer.microsoft.com/api/data/v1/item/bbox/' +
    bb + '.tif?collection=' + k.coll + '&item=' + encodeURIComponent(pass.id) +
    '&assets=' + k.assets;
}

function chipUrl(kind, pass, lon, lat, metres, px) {
  var k = CHIP_KIND[kind];
  var dLat = metres / 111320.0;
  var dLon = metres / (111320.0 * Math.cos(lat * Math.PI / 180));
  var bb = [lon - dLon / 2, lat - dLat / 2, lon + dLon / 2, lat + dLat / 2]
    .map(function (x) { return x.toFixed(6); }).join(',');
  var u = 'https://planetarycomputer.microsoft.com/api/data/v1/item/bbox/' +
    bb + '/' + px + 'x' + px + '.png?collection=' + k.coll +
    '&item=' + encodeURIComponent(pass.id) + '&assets=' + k.assets + k.extra;
  return (window.PROXY && PROXY.on) ? '/cache/img?u=' + encodeURIComponent(u) : u;
}

/* Enlace al visor oficial de Copernicus en ese punto y esa fecha: deja que
 * cualquiera verifique el recorte en la fuente, que es lo que separa una
 * prueba de una captura de pantalla. */
function copernicusUrl(lon, lat, tMs) {
  var d = new Date(tMs);
  var day = d.toISOString().slice(0, 10);
  return 'https://browser.dataspace.copernicus.eu/?zoom=14&lat=' + lat.toFixed(5) +
    '&lng=' + lon.toFixed(5) + '&fromTime=' + day + 'T00%3A00%3A00.000Z' +
    '&toTime=' + day + 'T23%3A59%3A59.999Z';
}

/* Devuelve el HTML del contenedor. El contenido se pinta en chipRender, que
 * es lo que vuelven a llamar los botones de tamano y de pasada. */
function chipHtml(lon, lat, tMs, kind, opts) {
  kind = kind || 's1';
  var id = 'chip' + (CHIP.seq += 1);
  CHIP.reg[id] = { lon: lon, lat: lat, t: tMs, kind: kind, m: 500, i: null,
                   tried: {}, dead: false,
                   /* `owner` ata el recorte al bloque de confirmacion: si
                    * aquel concluye que no hay pasada util, este se pliega
                    * con el en vez de quedarse solo enseñando un cuadro
                    * negro de una pasada de hace 19 horas. */
                   owner: (opts || {}).owner || null };
  CHIP.lastId = id;
  return '<div class="chip-box" id="' + id + '"></div>';
}

/* Colapsa todos los recortes atados a un bloque. */
function chipCollapseOwned(owner, reason) {
  Object.keys(CHIP.reg).forEach(function (id) {
    var st = CHIP.reg[id];
    if (st.owner !== owner) { return; }
    st.dead = true; st.deadReason = reason;
    if (document.getElementById(id)) { chipRender(id); }
  });
}

/* Una escena puede CUBRIR el punto por geometria y aun asi no tener pixeles
 * ahi: borde de franja, hueco de adquisicion, mascara. El resultado es un
 * cuadro negro que no informa de nada. Se detecta leyendo la imagen ya
 * cargada: si casi todas las muestras son identicas, no hay dato. */
function chipImageEmpty(img) {
  try {
    var n = 16;
    var cv = document.createElement('canvas');
    cv.width = n; cv.height = n;
    var cx = cv.getContext('2d');
    cx.drawImage(img, 0, 0, n, n);
    var d = cx.getImageData(0, 0, n, n).data;
    var vals = [], opaque = 0;
    for (var i = 0; i < d.length; i += 4) {
      if (d[i + 3] < 16) { continue; }       /* transparente = sin dato */
      opaque += 1;
      vals.push((d[i] + d[i + 1] + d[i + 2]) / 3);
    }
    if (opaque < n * n * 0.2) { return true; }
    var mu = vals.reduce(function (a, b) { return a + b; }, 0) / vals.length;
    var sd = Math.sqrt(vals.reduce(function (a, b) {
      return a + (b - mu) * (b - mu); }, 0) / vals.length);
    /* Mar en calma todavia tiene moteado: sd ~ 10 o mas. Un recorte sin dato
     * es plano, sd < 3, y suele ser negro del todo. */
    return sd < 3;
  } catch (e) {
    return false;        /* canvas contaminado: no se puede juzgar, se deja */
  }
}

function chipBind(id) {
  var st = CHIP.reg[id]; if (!st) { return; }
  var el = document.getElementById(id); if (!el) { return; }
  chipRender(id);
}

function chipRender(id) {
  var st = CHIP.reg[id]; if (!st) { return; }
  var el = document.getElementById(id); if (!el) { return; }
  var list = passesCovering(st.kind, st.lon, st.lat);
  var k = CHIP_KIND[st.kind];

  var head = '<div class="btn-row chip-kind">' +
      Object.keys(CHIP_KIND).map(function (kk) {
        return '<button class="btn' + (kk === st.kind ? ' primary' : '') +
          '" data-chip="' + id + '" data-kind="' + kk + '">' +
          esc(CHIP_KIND[kk].label.split(' ')[0] + ' ' +
              CHIP_KIND[kk].label.split(' ')[1]) + '</button>'; }).join('') +
    '</div>';

  var open = chipOpen(id);
  if (!window.PASSES || !PASSES.loaded) {
    el.className = 'chip-box';
    el.innerHTML = chipBar(id, st, t('chip_loading'));
    /* Cuando llegue el catalogo hay que volver a pintar: si no, el recorte
     * se queda en «cargando» para siempre en el buque que se abrio primero. */
    if (!st.waiting) {
      st.waiting = true;
      var tick = setInterval(function () {
        if (window.PASSES && PASSES.loaded) {
          clearInterval(tick); st.waiting = false;
          if (document.getElementById(id)) { chipRender(id); }
        }
      }, 700);
    }
    return;
  }
  if (st.dead || !list.length) {
    /* Nada que enseñar con ESTE sensor. La barra sigue ahi con el motivo, y
     * los botones de sensor dentro: cambiar a Sentinel-2 es justo lo que el
     * usuario va a querer hacer a continuacion. */
    var why = st.dead ? (st.deadReason || t('chip_empty_short')) : t('chip_none_short');
    el.className = 'chip-box quiet';
    el.innerHTML = chipBar(id, st, why) +
      (open ? '<div class="chip-body">' + head + '<p class="note empty">' +
        esc(st.dead ? t('chip_empty') : t('chip_none', { s: k.label })) +
        '</p></div>' : '');
    chipWire(id); return;
  }
  el.className = 'chip-box';
  if (st.i === null || st.i >= list.length) { st.i = nearestPassIndex(list, st.t); }
  if (!open) {
    el.innerHTML = chipBar(id, st, CHIP_KIND[st.kind].label + ' · ' +
      t('chip_of', { n: st.i + 1, m: list.length }));
    chipWire(id); return;
  }
  var pass = list[st.i];
  var dt = pass.t - st.t;
  var px = 300;
  var url = chipUrl(st.kind, pass, st.lon, st.lat, st.m, px);
  /* La barra de escala mide una fraccion conocida del recorte, asi que su
   * longitud en metros es exacta por construccion, no estimada. */
  var barM = st.m / 4;
  var barLabel = barM >= 1000 ? (barM / 1000) + ' km' : Math.round(barM) + ' m';

  el.innerHTML = chipBar(id, st, null) + '<div class="chip-body">' + head +
    '<div class="chip-img">' +
      '<img id="' + id + '-img" src="' + esc(url) + '" width="' + px +
        '" height="' + px + '" alt="' + esc(k.label) + '">' +
      '<svg class="chip-n" viewBox="0 0 40 46" aria-hidden="true">' +
        '<path d="M20 44 L20 10" stroke="#fff" stroke-width="2"/>' +
        '<path d="M20 4 L26 16 L20 12.5 L14 16 Z" fill="#fff"/>' +
        '<text x="20" y="44" fill="#fff" font-size="11" text-anchor="middle" ' +
          'dy="-34">N</text></svg>' +
      '<div class="chip-scale"><i style="width:25%"></i><span>' + barLabel +
        '</span></div>' +
      '<div class="chip-x"></div>' +
    '</div>' +
    '<div class="btn-row chip-ctl">' +
      '<button class="btn" data-chip="' + id + '" data-step="-1"' +
        (st.i <= 0 ? ' disabled' : '') + '>&larr;</button>' +
      '<span class="note chip-when">' + fmtUTC(pass.t) + ' · ' +
        (dt >= 0 ? '+' : '−') + fmtDur(Math.abs(dt)) + '</span>' +
      '<button class="btn" data-chip="' + id + '" data-step="1"' +
        (st.i >= list.length - 1 ? ' disabled' : '') + '>&rarr;</button>' +
    '</div>' +
    '<div class="btn-row chip-ctl">' +
      CHIP_SIZES.map(function (m) {
        return '<button class="btn' + (m === st.m ? ' primary' : '') +
          '" data-chip="' + id + '" data-m="' + m + '">' +
          (m >= 1000 ? (m / 1000) + ' km' : m + ' m') + '</button>'; }).join('') +
    '</div>' +
    '<div class="note">' + esc(t('chip_of', { n: st.i + 1, m: list.length })) +
      (pass.cloud !== undefined && pass.cloud !== null
        ? ' · ' + Math.round(pass.cloud) + '% cloud' : '') + '</div>' +
    '<div class="note mono chip-id">' + esc(pass.id) + '</div>' +
    '<div class="btn-row">' +
      (st.kind === 's1'
        ? '<button class="btn primary" data-chip="' + id + '" data-detect="1">' +
          esc(st.det ? t('chip_redetect') : t('chip_detect')) + '</button>' : '') +
      '<a class="btn" href="' + esc(copernicusUrl(st.lon, st.lat, pass.t)) +
      '" target="_blank" rel="noopener">' + esc(t('chip_browser')) + '</a></div>' +
    chipDetHtml(st) +
    '<p class="note">' + esc(t('chip_note')) + '</p></div>';
  chipWire(id);
}

/* Resultado del detector: cuantos blancos, y para cada uno si el AIS lo
 * explica. Un blanco SIN AIS a esa hora es la definicion operativa de buque
 * oscuro, y es el unico resultado que merece una alarma. */
function chipDetHtml(st) {
  if (st.detBusy) { return '<p class="note">' + esc(t('chip_detecting')) + '</p>'; }
  if (!st.det) { return ''; }
  if (st.det.error) {
    return '<p class="note empty">' + esc(st.det.error) + '</p>';
  }
  var f = st.det.features || [];
  if (!f.length) {
    var nland = (st.det.properties || {}).dropped_on_land || 0;
    return '<p class="note">' + esc(t('chip_det_none')) +
      (nland ? ' ' + esc(t('chip_land', { n: nland })) : '') + '</p>';
  }
  var dark = f.filter(function (x) { return !x.properties.ais_match; }).length;
  var land = (st.det.properties || {}).dropped_on_land || 0;
  return '<div class="block' + (dark ? ' caution' : '') + '"><h4>' +
    esc(t('chip_det_h', { n: f.length })) + '</h4>' +
    (land ? '<div class="note">' + esc(t('chip_land', { n: land })) + '</div>' : '') +
    (land ? '<div class="note empty">' + esc(t('chip_coast')) + '</div>' : '') +
    f.slice(0, 8).map(function (x) {
      var p = x.properties, m = p.ais_match;
      return '<div class="row"><span class="k">~' + p.length_m_estimate + ' m · ' +
        p.pixels + ' px · SNR ' + (p.snr_sigma || '?') + 'σ</span><span class="' +
        (m ? 'ok' : 'empty') + '">' +
        (m ? esc(m.name || ('MMSI ' + m.mmsi)) + ' · ' + Math.round(m.distance_m) + ' m'
           : esc(t('chip_dark'))) + '</span></div>'; }).join('') +
    (f.length > 8 ? '<div class="note">+' + (f.length - 8) + '</div>' : '') +
    '<p class="note">' + esc(t(dark ? 'chip_dark_note' : 'chip_det_note')) + '</p>' +
    '<p class="note">' + esc(f[0].properties.caveat) + '</p></div>';
}

/* Cruce con AIS: la posicion interpolada de cada buque en el instante EXACTO
 * de la adquisicion, no su ultimo fix. Un barco a 12 nudos recorre 370 m en
 * un minuto, asi que comparar contra el ultimo fix produciria «oscuros»
 * falsos a mansalva. */
function aisAt(mmsi, tMs) {
  var pts = (HIST[mmsi] || {}).pts;
  if (!pts || !pts.length) { return null; }
  var a = null, b = null;
  for (var i = 0; i < pts.length; i += 1) {
    if (pts[i].t <= tMs) { a = pts[i]; } else { b = pts[i]; break; }
  }
  if (a && b) {
    var f = (tMs - a.t) / Math.max(1, b.t - a.t);
    return { lon: a.lon + (b.lon - a.lon) * f, lat: a.lat + (b.lat - a.lat) * f,
             gap_s: Math.round((b.t - a.t) / 1000), interpolated: true };
  }
  var p = a || pts[0];
  var dt = Math.abs(p.t - tMs);
  if (dt > 30 * 60 * 1000) { return null; }      /* demasiado viejo para valer */
  return { lon: p.lon, lat: p.lat, gap_s: Math.round(dt / 1000), interpolated: false };
}

/* La tierra brilla en SAR tanto o mas que un casco. Sin mascara, un recorte
 * de 3 km sobre la costa devuelve decenas de «blancos» que son roca y
 * edificio. La rejilla de profundidad ya esta cargada, asi que el filtro
 * sale gratis: fuera del agua, no hay buque. */
/* Dos filtros, y hace falta el segundo. La rejilla de profundidad es de
 * 0,05 grados (~5 km): a 10 m de resolucion SAR no distingue una isla. La
 * costa derivada del DTM esta a 0,01 grados y sirve mucho mejor, asi que se
 * descarta todo lo que caiga a menos de COAST_MIN_M de ella.
 *
 * Esto no resuelve el problema del todo y conviene decirlo: un islote que no
 * este en la linea de costa sigue colandose. Cerca de tierra, el detector es
 * indicativo; en mar abierto es donde vale. */
var COAST_MIN_M = 200;

function onWater(lon, lat) {
  if (typeof distToCoastM === 'function' && distToCoastM(lon, lat) < COAST_MIN_M) {
    return false;
  }
  if (typeof depthAt === 'function') {
    var d = depthAt(lon, lat);
    if (d !== null && d !== undefined && d <= 0) { return false; }
  }
  return true;
}

function maskLand(fc) {
  var all = fc.features || [];
  var keep = all.filter(function (d) {
    return onWater(d.geometry.coordinates[0], d.geometry.coordinates[1]); });
  fc.properties = fc.properties || {};
  fc.properties.dropped_on_land = all.length - keep.length;
  fc.features = keep;
  return fc;
}

function matchDetections(fc, tMs, maxM) {
  (fc.features || []).forEach(function (d) {
    var c = d.geometry.coordinates, best = null;
    Object.keys(HIST).forEach(function (m) {
      var p = aisAt(m, tMs);
      if (!p) { return; }
      var dm = haversineM(c[0], c[1], p.lon, p.lat);
      if (dm <= maxM && (!best || dm < best.distance_m)) {
        best = { mmsi: m, name: (vinfo(m) || {}).name || HIST[m].name,
                 distance_m: dm, interpolated: p.interpolated };
      }
    });
    d.properties.ais_match = best;
  });
  return fc;
}

function haversineM(lon1, lat1, lon2, lat2) {
  var R = 6371000, p1 = lat1 * Math.PI / 180, p2 = lat2 * Math.PI / 180;
  var dp = p2 - p1, dl = (lon2 - lon1) * Math.PI / 180;
  var a = Math.sin(dp / 2) * Math.sin(dp / 2) +
          Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) * Math.sin(dl / 2);
  return 2 * R * Math.asin(Math.sqrt(a));
}

var DET_LAYER = null;
function drawDetections(fc) {
  if (DET_LAYER) { map.removeLayer(DET_LAYER); }
  DET_LAYER = L.layerGroup();
  (fc.features || []).forEach(function (d) {
    var c = d.geometry.coordinates, p = d.properties, m = p.ais_match;
    L.circleMarker([c[1], c[0]], { radius: 9, weight: 2,
      color: m ? '#58d68d' : '#ff4438', fillColor: 'transparent', fillOpacity: 0,
      dashArray: m ? null : '3 3' })
      .bindPopup('<h4>' + (m ? '' : '⚠ ') + esc(t('chip_det_one')) + '</h4>' +
        table({ length_m_estimate: p.length_m_estimate, pixels: p.pixels,
                snr_sigma: p.snr_sigma, peak_dn: p.peak_dn,
                ais: m ? (m.name || m.mmsi) + ' @ ' + Math.round(m.distance_m) + ' m'
                       : t('chip_dark') }) +
        '<p class="note">' + esc(p.caveat) + '</p>')
      .addTo(DET_LAYER);
  });
  DET_LAYER.addTo(map);
  layers.sar_detections = DET_LAYER;
  if (window.renderLayers) { renderLayers(); }
}

function chipDetect(id) {
  var st = CHIP.reg[id]; if (!st) { return; }
  var list = passesCovering(st.kind, st.lon, st.lat);
  if (!list.length) { return; }
  var pass = list[st.i];
  st.detBusy = true; st.det = null; chipRender(id);
  var tif = chipTifUrl(st.kind, pass, st.lon, st.lat, st.m);
  var url = (window.PROXY && PROXY.on)
    ? '/cache/detect?u=' + encodeURIComponent(tif) : null;
  if (!url) {
    st.detBusy = false;
    st.det = { error: t('chip_det_proxy') };
    chipRender(id); return;
  }
  fetch(url).then(function (r) { return r.json(); }).then(function (fc) {
    if (fc.error) { throw new Error(fc.error); }
    maskLand(fc);
    /* El margen de emparejamiento crece con el recorte: en 3 km el error de
     * geolocalizacion y la interpolacion AIS pesan mas. */
    matchDetections(fc, pass.t, Math.max(150, st.m / 4));
    st.det = fc; st.detBusy = false;
    drawDetections(fc);
    chipRender(id);
  }).catch(function (e) {
    st.detBusy = false; st.det = { error: String(e.message || e) };
    chipRender(id);
  });
}

/* ============================ confirmacion SAR del historial de posiciones */
/* El boton suelto de «detectar» no decia nada util: una lista de blancos sin
 * contexto. Lo que SI dice algo es cruzarlo con la derrota de UN buque.
 *
 * Para cada pasada Sentinel-1 que cubra la derrota en su ventana temporal, se
 * recorta 1 km alrededor de donde el AIS dice que estaba el buque EN ESE
 * INSTANTE y se corre CFAR. Si aparece un blanco a menos del margen, dos
 * sensores independientes —AIS cooperativo y radar no cooperativo— situan al
 * mismo buque en el mismo sitio a la misma hora. Eso es confirmacion; lo
 * contrario, con satelite encima, es un hueco que merece explicacion. */
var CONFIRM = { layer: null, rows: [], busy: false, mmsi: null };
var CONFIRM_CROP_M = 1000;
var CONFIRM_MATCH_M = 300;

function confirmClear() {
  if (CONFIRM.layer) { map.removeLayer(CONFIRM.layer); }
  CONFIRM = { layer: null, rows: [], busy: false, mmsi: null };
  delete layers.sar_confirm;
}

/* Pasadas que cubren el punto Y caen dentro de la ventana de la derrota. */
function passesForTrack(pts) {
  if (!pts.length) { return []; }
  var t0 = pts[0].t, t1 = pts[pts.length - 1].t;
  return ((window.PASSES && PASSES.s1) || []).filter(function (p) {
    if (p.t < t0 || p.t > t1) { return false; }
    var at = aisAt(CONFIRM.mmsi, p.t);
    if (!at) { return false; }
    var g = geomContains(p.geom, at.lon, at.lat);
    return g === null ? true : g;
  });
}

function confirmTrack(mmsi, pts, onProgress) {
  confirmClear();
  CONFIRM.mmsi = String(mmsi);
  if (!window.PROXY || !PROXY.on) {
    CONFIRM.rows = [{ error: t('chip_det_proxy') }];
    if (onProgress) { onProgress(CONFIRM); }
    return Promise.resolve(CONFIRM);
  }
  var list = passesForTrack(pts);
  CONFIRM.busy = true;
  CONFIRM.total = list.length;
  if (onProgress) { onProgress(CONFIRM); }
  if (!list.length) {
    CONFIRM.busy = false;
    if (onProgress) { onProgress(CONFIRM); }
    return Promise.resolve(CONFIRM);
  }
  /* En serie, no en paralelo: cada recorte son ~2 s de CFAR en el servidor y
   * lanzar diez a la vez solo consigue que el navegador espere lo mismo con
   * el mapa congelado. Asi cada resultado se pinta en cuanto llega. */
  var i = 0;
  var step = function () {
    if (i >= list.length) {
      CONFIRM.busy = false;
      if (onProgress) { onProgress(CONFIRM); }
      return Promise.resolve(CONFIRM);
    }
    var pass = list[i]; i += 1;
    var at = aisAt(CONFIRM.mmsi, pass.t);
    var tif = chipTifUrl('s1', pass, at.lon, at.lat, CONFIRM_CROP_M);
    return fetch('/cache/detect?u=' + encodeURIComponent(tif))
      .then(function (r) { return r.json(); })
      .then(function (fc) {
        var best = null;
        (fc.features || []).forEach(function (d) {
          var c = d.geometry.coordinates;
          if (!onWater(c[0], c[1])) { return; }
          var dm = haversineM(c[0], c[1], at.lon, at.lat);
          if (dm <= CONFIRM_MATCH_M && (!best || dm < best.distance_m)) {
            best = { lon: c[0], lat: c[1], distance_m: dm,
                     length_m: d.properties.length_m_estimate,
                     snr: d.properties.snr_sigma, pixels: d.properties.pixels };
          }
        });
        CONFIRM.rows.push({ t: pass.t, scene: pass.id, ais: at, hit: best,
                            targets: (fc.features || []).length });
        drawConfirm();
        if (onProgress) { onProgress(CONFIRM); }
      })
      .catch(function (e) {
        CONFIRM.rows.push({ t: pass.t, scene: pass.id, ais: at,
                            error: String(e.message || e) });
        if (onProgress) { onProgress(CONFIRM); }
      })
      .then(step);
  };
  return step();
}

function drawConfirm() {
  if (CONFIRM.layer) { map.removeLayer(CONFIRM.layer); }
  CONFIRM.layer = L.layerGroup();
  CONFIRM.rows.forEach(function (r) {
    if (r.error) { return; }
    if (r.hit) {
      /* Confirmado por dos sensores: cian brillante, el color mas visible
       * que no choca con el magenta del historial ni con el rojo de alerta. */
      L.circleMarker([r.ais.lat, r.ais.lon], { radius: 13, color: '#00e5ff',
        weight: 3, fillColor: '#00e5ff', fillOpacity: 0.12 })
        .bindPopup(confirmPopup(r))
        .on('popupopen', function (e) {
          bindVerdictButtons(e.popup.getElement(), r); })
        .addTo(CONFIRM.layer);
      L.polyline([[r.ais.lat, r.ais.lon], [r.hit.lat, r.hit.lon]],
        { color: '#00e5ff', weight: 2, dashArray: '3 3' }).addTo(CONFIRM.layer);
      L.circleMarker([r.hit.lat, r.hit.lon], { radius: 5, color: '#00e5ff',
        weight: 2, fillColor: '#06101a', fillOpacity: 1 }).addTo(CONFIRM.layer);
      L.marker([r.ais.lat, r.ais.lon], { interactive: false, icon: L.divIcon({
        className: 'rtag confirmed', iconSize: null, iconAnchor: [0, 38],
        html: '<b>SAR ✓</b><span>' + fmtUTC(r.t).slice(11) + '</span>' }) })
        .addTo(CONFIRM.layer);
    } else {
      /* Satelite encima y nada detectado. No es prueba de nada por si solo
       * —mar gruesa, buque pequeno, angulo— pero es exactamente el hueco que
       * hay que mirar. */
      L.circleMarker([r.ais.lat, r.ais.lon], { radius: 10, color: '#ffb02e',
        weight: 2, dashArray: '4 3', fillOpacity: 0 })
        .bindPopup(confirmPopup(r))
        .on('popupopen', function (e) {
          bindVerdictButtons(e.popup.getElement(), r); })
        .addTo(CONFIRM.layer);
    }
  });
  CONFIRM.layer.addTo(map);
  layers.sar_confirm = CONFIRM.layer;
}

/* --------------------------------- veredicto del operador sobre un blanco */
/* El detector puede equivocarse y el unico que puede decirlo es quien mira la
 * imagen. Los veredictos se guardan en el navegador y se pueden exportar:
 * eso convierte el uso diario en el conjunto etiquetado que hoy no existe y
 * sin el cual los umbrales no se pueden calibrar. */
var VERDICT_KEY = 'custody.sarVerdicts';

function verdictKey(r) {
  return r.scene + '@' + r.ais.lon.toFixed(5) + ',' + r.ais.lat.toFixed(5);
}
function verdictsAll() {
  try { return JSON.parse(localStorage.getItem(VERDICT_KEY) || '{}'); }
  catch (e) { return {}; }
}
function verdictGet(r) { return verdictsAll()[verdictKey(r)] || null; }
function verdictSet(r, v) {
  var all = verdictsAll();
  if (v) {
    all[verdictKey(r)] = { v: v, t: Date.now(), scene: r.scene,
                           lon: r.ais.lon, lat: r.ais.lat,
                           sar_offset_m: r.hit ? Math.round(r.hit.distance_m) : null,
                           sar_length_m: r.hit ? r.hit.length_m : null,
                           snr: r.hit ? r.hit.snr : null };
  } else { delete all[verdictKey(r)]; }
  try { localStorage.setItem(VERDICT_KEY, JSON.stringify(all)); } catch (e) {}
}

/* Descarga los veredictos como JSON. Sin esto el feedback seria teatro: se
 * quedaria en el navegador y no serviria para calibrar nada. */
function verdictExport() {
  var all = verdictsAll();
  var rows = Object.keys(all).map(function (k) { return dict2(k, all[k]); });
  var blob = new Blob([JSON.stringify({ exported: new Date().toISOString(),
    n: rows.length, verdicts: rows }, null, 1)], { type: 'application/json' });
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'sar-verdicts-' + new Date().toISOString().slice(0, 10) + '.json';
  a.click();
  setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
}
function dict2(k, v) { return Object.assign({ key: k }, v); }

/* ------------------------------------------------ popup de confirmacion */
function confirmPopup(r) {
  var yes = !!r.hit;
  var h = '<h4>' + (yes ? '✓ ' + esc(t('cf_yes')) : '⚠ ' + esc(t('cf_no'))) + '</h4>' +
    '<div class="note">' + fmtUTC(r.t) + '</div>';

  /* La imagen, con el blanco recuadrado. Es la unica forma de que quien mira
   * pueda decir si hay un barco o es un falso positivo: el numero solo no
   * permite juzgar nada. */
  var pass = ((window.PASSES && PASSES.s1) || []).filter(function (p) {
    return p.id === r.scene; })[0];
  /* La imagen se pinta SIEMPRE, haya blanco o no. Cuando no lo hay es cuando
   * mas falta hace: solo mirando el recorte puede alguien decir si el
   * detector se dejo algo o si de verdad ahi no habia nada. */
  if (pass) {
    var px = 260, m = CONFIRM_CROP_M;
    var url = chipUrl('s1', pass, r.ais.lon, r.ais.lat, m, px);
    var dLat = m / 111320.0;
    var dLon = m / (111320.0 * Math.cos(r.ais.lat * Math.PI / 180));
    var box = '';
    if (yes) {
      /* El recuadro se situa por geometria, no a ojo: del desfase en grados
       * entre el blanco y el centro del recorte, que es la posicion AIS. */
      var fx = 0.5 + (r.hit.lon - r.ais.lon) / dLon;
      var fy = 0.5 - (r.hit.lat - r.ais.lat) / dLat;
      var sz = Math.max(9, Math.min(40, 100 * (r.hit.length_m || 60) / m));
      box = '<i class="det-box" style="left:' + (100 * fx) + '%;top:' + (100 * fy) +
        '%;width:' + sz + '%;height:' + sz + '%"></i>';
    }
    h += '<div class="cf-img">' +
      '<img src="' + esc(url) + '" width="' + px + '" height="' + px +
        '" alt="Sentinel-1">' + box +
      '<i class="det-ais' + (yes ? '' : ' alone') + '" title="AIS"></i>' +
      '<div class="chip-scale"><i style="width:25%"></i><span>' +
        Math.round(m / 4) + ' m</span></div>' +
      '</div>';
  }

  h += table({ ais_lon: r.ais.lon.toFixed(5), ais_lat: r.ais.lat.toFixed(5),
               ais_interpolated: r.ais.interpolated,
               sar_offset_m: r.hit ? Math.round(r.hit.distance_m) : null,
               sar_length_m: r.hit ? r.hit.length_m : null,
               sar_snr: r.hit ? r.hit.snr : null,
               targets_in_crop: r.targets });
  h += '<p class="note">' + esc(t(r.hit ? 'cf_yes_note' : 'cf_no_note')) + '</p>';

  /* Procedencia linea a linea. Lo que es medido, lo que es interpolado y lo
   * que lo calcula esta herramienta, separado y con su fuente. */
  h += '<details class="prov"><summary>' + esc(t('prov_h')) + '</summary>' +
    '<div class="inner">' +
    '<div class="row"><span class="k">' + esc(t('prov_ais')) + '</span><span>' +
      esc(t('prov_ais_src')) + '</span></div>' +
    (r.ais.interpolated
      ? '<p class="note empty">' + esc(t('prov_interp')) + '</p>' : '') +
    '<div class="row"><span class="k">' + esc(t('prov_img')) + '</span><span>' +
      esc(t('prov_img_src')) + '</span></div>' +
    '<div class="note mono">' + esc(r.scene) + '</div>' +
    '<div class="row"><span class="k">' + esc(t('prov_det')) + '</span><span>' +
      esc(t('prov_det_src')) + '</span></div>' +
    '<p class="note">' + esc(t('prov_cfar')) + '</p>' +
    '<p class="note"><b>' + esc(t('prov_concl')) + '</b></p>' +
    '</div></details>';

  /* Veredicto del operador. */
  var cur = verdictGet(r);
  h += '<div class="cf-fb"><span class="note">' + esc(t('fb_q')) + '</span>' +
    '<div class="btn-row">' +
    ['ship', 'false', 'unsure'].map(function (v) {
      return '<button class="btn fb' + (cur && cur.v === v ? ' primary' : '') +
        '" data-fb="' + v + '" data-fbkey="' + esc(verdictKey(r)) + '">' +
        esc(t('fb_' + v)) + '</button>'; }).join('') +
    '</div></div>';
  return h;
}

/* El popup se monta y desmonta con Leaflet, asi que los botones se atan al
 * abrirse, no al construir el HTML. */
function bindVerdictButtons(el, r) {
  el.querySelectorAll('[data-fb]').forEach(function (b) {
    b.addEventListener('click', function () {
      var v = b.dataset.fb;
      var cur = verdictGet(r);
      verdictSet(r, cur && cur.v === v ? null : v);
      el.querySelectorAll('[data-fb]').forEach(function (x) {
        x.classList.toggle('primary',
          x.dataset.fb === v && !(cur && cur.v === v));
      });
    });
  });
}


function chipWire(id) {
  var el = document.getElementById(id); if (!el) { return; }
  /* Probar la imagen en cuanto cargue. Si esta vacia se salta a la siguiente
   * pasada: que la decima no tenga pixeles aqui no dice nada de la novena.
   * Tras agotar las que cubren el punto, se pliega. */
  var img = document.getElementById(id + '-img');
  if (img) {
    img.addEventListener('load', function () {
      var st = CHIP.reg[id]; if (!st || st.dead) { return; }
      if (!chipImageEmpty(img)) { return; }
      st.tried[st.i] = true;
      var list = passesCovering(st.kind, st.lon, st.lat);
      var next = -1;
      for (var j = 0; j < list.length; j += 1) {
        if (!st.tried[j]) { next = j; break; }
      }
      if (next < 0) { st.dead = true; st.deadReason = t('chip_empty_short'); }
      else { st.i = next; }
      chipRender(id);
    });
    img.addEventListener('error', function () {
      var st = CHIP.reg[id]; if (!st) { return; }
      st.dead = true; st.deadReason = t('chip_empty_short');
      chipRender(id);
    });
  }
  el.querySelectorAll('[data-chip]').forEach(function (b) {
    b.addEventListener('click', function () {
      var st = CHIP.reg[id];
      if (b.dataset.detect) { chipDetect(id); return; }
      if (b.dataset.toggle) { chipSetOpen(id, !chipOpen(id)); return; }
      if (b.dataset.kind) {
        st.kind = b.dataset.kind; st.i = null; st.det = null;
        st.tried = {}; st.dead = false; st.deadReason = null;
        chipSetOpen(id, true);
      }
      else if (b.dataset.m) { st.m = +b.dataset.m; st.det = null; st.tried = {}; st.dead = false; }
      else if (b.dataset.step) { st.i += (+b.dataset.step); st.det = null; }
      chipRender(id);
    });
  });
}

proxyProbe();
