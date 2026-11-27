/* depthmap.js - batimetria del Baltico pintada con una paleta propia.
 *
 * POR QUE NO VALE LA DEL WMS
 * --------------------------
 * La rampa oficial de EMODnet va de -6000 m a 0. Medido sobre nuestra propia
 * rejilla: la mediana del Baltico son 48 m, el p75 son 89 m y el 85 % del mar
 * es mas somero que 120 m. O sea que TODO el Baltico cae en el ultimo 2 % de
 * esa escala, y el violeta -- medio espectro -- se gasta en profundidades que
 * aqui no existen. El servicio ignora COLORSCALERANGE, asi que no se puede
 * reescalar desde fuera.
 *
 * COMO SE ELIGIERON LOS CORTES
 * ----------------------------
 * Por CUANTILES de la propia rejilla, no a ojo: cada banda se lleva entre el
 * 3 % y el 19 % del area, asi que ninguna domina y el contraste es maximo
 * justo donde hay dato. Medido 2026-11-11 sobre 20.524 celdas con agua:
 *
 *     0-10 m  11.3 %   50- 80 m  18.8 %   200-300 m   2.9 %
 *    10-20 m  12.1 %   80-120 m  15.3 %   300+   m   3.3 %
 *    20-30 m  10.8 %  120-200 m   8.0 %
 *    30-50 m  16.9 %
 *
 * El corte de 100 m no es estetico: es donde deja de ser practico fondear un
 * mercante, que es la pregunta que hace toda esta herramienta. Se marca con
 * un salto de color deliberado (azul -> indigo).
 *
 * SOLO SE PINTA EL MAR. La rejilla trae null en tierra, y null se queda
 * transparente. No hay que recortar nada.
 */
'use strict';

var DEPTH_BANDS = [
  { max: 10,   c: [214, 240, 231], label: '0–10 m' },
  { max: 20,   c: [143, 217, 192], label: '10–20 m' },
  { max: 30,   c: [ 79, 195, 161], label: '20–30 m' },
  { max: 50,   c: [ 42, 157, 143], label: '30–50 m' },
  { max: 80,   c: [ 42, 127, 158], label: '50–80 m' },
  { max: 120,  c: [ 43,  95, 158], label: '80–120 m' },
  { max: 200,  c: [ 59,  63, 143], label: '120–200 m' },
  { max: 300,  c: [ 91,  47, 143], label: '200–300 m' },
  { max: 1e9,  c: [142,  47, 158], label: '300 m +' }
];
/* Por encima de esto dejar de ser realista fondear un mercante. Es el unico
 * corte de la escala que significa algo operativo y se senala aparte. */
var ANCHOR_LIMIT_M = 100;

var DEPTHMAP = { layer: null };

function depthColour(d) {
  for (var i = 0; i < DEPTH_BANDS.length; i += 1) {
    if (d < DEPTH_BANDS[i].max) { return DEPTH_BANDS[i].c; }
  }
  return DEPTH_BANDS[DEPTH_BANDS.length - 1].c;
}

/* El build emite data/depth_map.png ya PROYECTADO en Web Mercator y a partir
 * de los GeoTIFF nativos de EMODnet (~116 m), no de la rejilla de trabajo.
 * Aqui solo se cuelga en sus esquinas.
 *
 * No hay respaldo pintando en canvas. Lo hubo, y era peor que no tener
 * ninguno: reimplementaba la reproyeccion en JS, asi que habia dos sitios
 * donde equivocarse con lo mismo. Si falta el PNG se dice y punto.
 */
function loadDepthMap() {
  if (DEPTHMAP.layer) { return Promise.resolve(DEPTHMAP.layer); }
  return fetch('data/depth_map.json')
    .then(function (r) { if (!r.ok) { throw new Error('no depth_map.json'); } return r.json(); })
    .then(function (m) {
      DEPTHMAP.meta = m;
      DEPTHMAP.layer = L.imageOverlay('data/depth_map.png',
        [[m.lat0, m.lon0], [m.lat1, m.lon1]],
        { opacity: 0.88, interactive: false, zIndex: 15, className: 'depth-raster',
          attribution: 'EMODnet Bathymetry DTM · palette calibrated to Baltic depths' });
      return DEPTHMAP.layer;
    })
    .catch(function (e) { DEPTHMAP.error = e.message; return null; });
}

function depthMapOn(on) {
  if (on) {
    loadDepthMap().then(function (l) {
      /* Puede haberlo apagado mientras bajaba el PNG. */
      if (l && document.getElementById('depthmap').checked) {
        l.addTo(map); layers.depthmap = l;
      }
      renderDepthLegend(on);
    });
  } else if (DEPTHMAP.layer) {
    map.removeLayer(DEPTHMAP.layer);
    delete layers.depthmap;
  }
  renderDepthLegend(on);
  if (window.renderLayers) { renderLayers(); }
}

function renderDepthLegend(on) {
  var box = document.getElementById('depth-legend'); if (!box) { return; }
  if (!on) { box.innerHTML = ''; box.hidden = true; return; }
  box.hidden = false;
  if (!DEPTHMAP.layer) {
    box.innerHTML = '<p class="note empty">' + esc(t('dm_missing')) + '</p>';
    return;
  }
  box.innerHTML = '<div class="dleg">' +
    '<div class="k">' + esc(t('dm_h')) + '</div>' +
    DEPTH_BANDS.map(function (b, i) {
      var anchor = (b.max === 120);
      return '<div class="dleg-row' + (anchor ? ' anchor' : '') + '">' +
        '<i style="background:rgb(' + b.c.join(',') + ')"></i>' +
        '<span>' + esc(b.label) + '</span>' +
        (anchor ? '<em>' + esc(t('dm_anchor')) + '</em>' : '') + '</div>'; }).join('') +
    '<p class="note">' + esc(t('dm_note')) + '</p>' +
    (DEPTHMAP.meta ? '<p class="note">' + esc(t('dm_res')) + ': ' +
      DEPTHMAP.meta.nx + ' x ' + DEPTHMAP.meta.ny + ' px · ' +
      Math.round((DEPTHMAP.meta.lon1 - DEPTHMAP.meta.lon0) /
                 DEPTHMAP.meta.nx * 111320 * 0.5) + ' m/px</p>' : '') +
    '</div>';
}
