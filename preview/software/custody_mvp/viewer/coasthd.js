/* coasthd.js - la linea de costa de HELCOM, bajo demanda.
 *
 * POR QUE HAY DOS LINEAS DE COSTA.
 *
 * `coastline.geojson` se deriva en el build de la mascara tierra/agua del DTM
 * de EMODnet. Eso se hizo antes de mirar si alguien ya la publicaba, y es el
 * orden equivocado: HELCOM la publica, y es 375 veces mas fina.
 *
 *   derivada por nosotros   paso 0,03 grados  ~3 km   455 kB  todo el Baltico
 *   HELCOM (MADS/Background/13)       mediana entre vertices 8 m
 *
 * Lo que NO se puede hacer es importarla entera: un recuadro de 1x0,5 grados
 * son 3,7 MB a resolucion nativa, o sea del orden de 1,8 GB para el AOI.
 *
 * Lo que SI, y es para lo que esta hecho el servicio: pedir solo el recuadro
 * visible, y pedirlo GENERALIZADO. El parametro `maxAllowableOffset` de
 * ArcGIS simplifica en el servidor antes de enviar: el mismo recuadro pasa de
 * 3,7 MB a 254 kB. Se pide en celdas de 0,5 grados alineadas a una rejilla
 * --no al encuadre exacto-- para que dos vistas parecidas pidan la MISMA URL
 * y la cache de disco del proxy acierte.
 *
 * Asi que se quedan las dos, cada una donde gana: la derivada para la vista
 * de conjunto (pequena, instantanea, sin red) y la de HELCOM al acercarse,
 * que es cuando 3 km de resolucion se notan y estorban.
 */
'use strict';

var COAST = { layer: null, cells: {}, polys: {}, active: {}, on: false,
              pend: 0, err: null };

var COAST_URL = 'https://maps.helcom.fi/arcgis/rest/services/MADS/Background/' +
                'MapServer/13/query';
var COAST_MIN_ZOOM = 5;     /* es la unica costa que hay: no puede no dibujarse */
/* Longitud minima de una pieza de costa para que valga la pena dibujarla,
 * en km, segun el zoom. A escala de conjunto una isla de 2 km es un punto. */
function coastMinKm(z) {
  if (z >= 11) { return 0; }
  if (z >= 9) { return 0.5; }
  if (z >= 7) { return 2; }
  return 8;
}

function pathKm(p) {
  var s = 0;
  for (var i = 1; i < p.length; i += 1) {
    var dx = (p[i][0] - p[i - 1][0]) * 55.0, dy = (p[i][1] - p[i - 1][1]) * 111.2;
    s += Math.sqrt(dx * dx + dy * dy);
  }
  return s;
}

function coastCellSize(z) {
  /* Celdas grandes al alejarse: a zoom 6 el mapa abarca el Baltico entero y
   * pedirlo en cuadros de medio grado serian cientos de peticiones. */
  return z >= 10 ? 0.5 : (z >= 8 ? 1 : 4);
}

/* Cuanto generalizar, en grados, segun el zoom. Pedir 8 m de detalle para
 * dibujarlo a 150 m por pixel es gastar red en vertices que no se ven. */
function coastOffset(z) {
  if (z >= 12) { return 0.0002; }
  if (z >= 10) { return 0.0005; }
  if (z >= 8) { return 0.002; }
  return 0.01;              /* vista de conjunto: el islote no se ve igual */
}

function coastCells(b, z) {
  var out = [], cell = coastCellSize(z);
  var x0 = Math.floor(b.getWest() / cell) * cell;
  var y0 = Math.floor(b.getSouth() / cell) * cell;
  for (var x = x0; x < b.getEast(); x += cell) {
    for (var y = y0; y < b.getNorth(); y += cell) {
      out.push([Math.round(x * 100) / 100, Math.round(y * 100) / 100,
                coastOffset(z), cell]);
    }
  }
  return out;
}

function coastKey(c, minKm) {
  return c[0] + ',' + c[1] + ',' + c[2] + ',' + c[3] + ',' + minKm;
}

function coastAttach(key) {
  var poly = COAST.polys[key];
  if (!poly || poly === 'empty' || !COAST.layer || COAST.active[key]) { return; }
  poly.addTo(COAST.layer);
  COAST.active[key] = poly;
}

function coastFetchCell(c, minKm) {
  if (minKm === undefined) { minKm = coastMinKm(map.getZoom()); }
  var key = coastKey(c, minKm);
  if (COAST.cells[key] === 'done') {
    coastAttach(key);
    return Promise.resolve();
  }
  if (COAST.cells[key] === 'loading') { return Promise.resolve(); }
  COAST.cells[key] = 'loading';
  var url = COAST_URL + '?' + [
    'geometry=' + [c[0], c[1], c[0] + c[3], c[1] + c[3]].join(','),
    'geometryType=esriGeometryEnvelope', 'inSR=4326',
    'spatialRel=esriSpatialRelIntersects', 'returnGeometry=true',
    'outSR=4326', 'maxAllowableOffset=' + c[2], 'f=json'
  ].join('&');
  var via = (window.PROXY && PROXY.on)
    ? '/cache/geo?u=' + encodeURIComponent(url) : url;
  COAST.pend += 1;
  return fetch(via).then(function (r) { return r.json(); }).then(function (d) {
    if (d.error) { throw new Error(d.error.message || 'ArcGIS'); }
    /* Filtrar islotes AQUI, no solo en el build, y agrupar todas las lineas de
     * la celda en UNA sola multipolilinea de Leaflet en vez de miles de capas
     * sueltas. Al cambiar de zoom, coastRefresh retira las celdas de otras
     * resoluciones para no apilar 500.000 vertices en el mismo canvas. */
    var rings = [];
    (d.features || []).forEach(function (f) {
      ((f.geometry && f.geometry.paths) || []).forEach(function (p) {
        if (p.length > 1 && pathKm(p) >= minKm) {
          rings.push(p.map(function (q) { return [q[1], q[0]]; }));
        }
      });
    });
    COAST.cells[key] = 'done';
    COAST.polys[key] = rings.length
      ? L.polyline(rings, { color: '#7fa6c4', weight: 1, opacity: 0.85,
                            interactive: false, smoothFactor: 1.5 })
      : 'empty';
    if (COAST.on && COAST.want && COAST.want[key]) { coastAttach(key); }
  }).catch(function (e) {
    COAST.cells[key] = null;           /* se podra reintentar */
    COAST.err = e.message;
  }).then(function () {
    COAST.pend -= 1;
    coastStatus();
  });
}

function coastRefresh() {
  if (!COAST.on) { return; }
  var z = map.getZoom();
  if (z < COAST_MIN_ZOOM) { coastStatus(); return; }
  var minKm = coastMinKm(z);
  var cells = coastCells(map.getBounds(), z);
  /* Del CENTRO hacia fuera. Antes se cortaba la lista en orden de
   * generacion, que es suroeste primero: a zoom 5 eso pedia doce cuadros de
   * oceano vacio y no llegaba nunca al Baltico, asi que la capa salia
   * encendida y sin una sola linea. */
  var c = map.getCenter();
  cells.sort(function (a, b) {
    var da = Math.pow(a[0] + a[3] / 2 - c.lng, 2) + Math.pow(a[1] + a[3] / 2 - c.lat, 2);
    var db = Math.pow(b[0] + b[3] / 2 - c.lng, 2) + Math.pow(b[1] + b[3] / 2 - c.lat, 2);
    return da - db;
  });
  var want = {};
  cells.forEach(function (cell) { want[coastKey(cell, minKm)] = 1; });
  COAST.want = want;
  if (COAST.layer && COAST.layer.removeLayer) {
    Object.keys(COAST.active).forEach(function (k) {
      if (!want[k]) {
        COAST.layer.removeLayer(COAST.active[k]);
        delete COAST.active[k];
      }
    });
  }
  /* Un techo por movimiento: alejarse de golpe no puede disparar doscientas
   * peticiones. Si falta algo, el siguiente movimiento lo trae. */
  cells.slice(0, 12).forEach(function (cell) { coastFetchCell(cell, minKm); });
  coastStatus();
}

function coastStatus() {
  var el = document.getElementById('coasthd-status');
  if (!el) { return; }
  if (!COAST.on) { el.textContent = ''; return; }
  var done = Object.keys(COAST.cells).filter(function (k) {
    return COAST.cells[k] === 'done'; }).length;
  if (map.getZoom() < COAST_MIN_ZOOM) {
    el.textContent = t('coast_zoom', { z: COAST_MIN_ZOOM });
  } else if (COAST.pend) {
    el.textContent = t('coast_loading', { n: COAST.pend });
  } else {
    el.textContent = COAST.err ? t('coast_err', { e: COAST.err })
                               : t('coast_ok', { n: done });
  }
}

function coastHdOn(on) {
  COAST.on = on;
  if (on) {
    if (!COAST.layer) {
      COAST.layer = L.layerGroup();
      layers.coast_hd = COAST.layer;
    }
    COAST.layer.addTo(map);
    coastRefresh();
  } else if (COAST.layer) {
    map.removeLayer(COAST.layer);
  }
  coastStatus();
  if (window.renderLayers) { renderLayers(); }
}
