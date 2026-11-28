/* ui.js - branding, language, the Learn tab y la gamificacion ligera.
 * Loaded after app.js so it can re-render what app.js already drew. */
'use strict';

var LS = { team: 'custody.team', lang: 'custody.lang',
           seen: 'custody.seen', tz: 'custody.tz',
           panels: 'custody.panels', mapkey: 'custody.mapkey' };

/* Paneles flotantes. Por defecto solo la barra de tiempo y la leyenda: el
 * resto estorba hasta que se pide. El estado se recuerda en el navegador. */
var PANEL_DEFAULT = { srcstrip: true, legend: true, timebar: true, basinbar: true };

function panelState() {
  try { return Object.assign({}, PANEL_DEFAULT,
    JSON.parse(localStorage.getItem(LS.panels) || '{}')); }
  catch (e) { return Object.assign({}, PANEL_DEFAULT); }
}
function applyPanels() {
  var st = panelState();
  Object.keys(PANEL_DEFAULT).forEach(function (k) {
    var el = document.getElementById(k);
    if (el) { el.hidden = !st[k]; }
    var btn = document.querySelector('[data-toggle="' + k + '"]');
    if (btn) { btn.classList.toggle('on', !!st[k]); }
  });
}
function togglePanel(k, force) {
  var st = panelState();
  st[k] = (force === undefined) ? !st[k] : !!force;
  try { localStorage.setItem(LS.panels, JSON.stringify(st)); } catch (e) {}
  applyPanels();
  /* Al encender, un destello breve. Varios paneles flotan sobre el mapa y
   * pulsar un boton sin ver QUE aparecio se siente como que no hizo nada,
   * sobre todo si el panel ya estaba visible y lo que hiciste fue apagarlo. */
  if (st[k]) {
    var el = document.getElementById(k);
    if (el) {
      el.classList.remove('flash');
      void el.offsetWidth;            /* reinicia la animacion */
      el.classList.add('flash');
      setTimeout(function () { el.classList.remove('flash'); }, 1200);
    }
  }
}

/* ------------------------------------------------------------ language */
function applyI18n() {
  document.documentElement.lang = LANG;
  document.querySelectorAll('[data-i18n]').forEach(function (el) {
    el.textContent = t(el.dataset.i18n);
  });
  /* El rail muestra el texto dentro del boton y tambien como tooltip y como
   * etiqueta accesible; las tres salen de la misma clave. */
  document.querySelectorAll('#activitybar button').forEach(function (b) {
    var lbl = b.querySelector('.rail-lbl');
    if (!lbl) { return; }
    b.title = lbl.textContent;
    b.setAttribute('aria-label', lbl.textContent);
    if (b.classList.contains('on')) {
      var st = document.getElementById('section-title');
      if (st) { st.textContent = lbl.textContent; }
    }
  });
  renderLegend();
  bindCloses();
  renderLearn();
  renderBadges();
  if (window.rerenderAlerts) { window.rerenderAlerts(); }
  if (window.renderVesselTab) { renderVesselTab(''); }
  if (window.renderTimeBar && TIME && TIME.t1) { renderTimeBar(); }
  if (window.renderSources) { renderSources(); renderSourceStrip(); }
  if (window.renderBasinBar) { renderBasinBar(); }
}

function bindCloses() {
  document.querySelectorAll('[data-close]').forEach(function (b) {
    if (b.dataset.bound) { return; }
    b.dataset.bound = '1';
    b.addEventListener('click', function () { togglePanel(b.dataset.close, false); });
  });
}

function setLang(code) {
  if (!STRINGS[code]) { code = 'en'; }
  LANG = code;
  try { localStorage.setItem(LS.lang, code); } catch (e) {}
  applyI18n();
  /* applyI18n solo toca lo que lleva data-i18n. Estas dos leyendas se
   * construyen con innerHTML y t(), asi que al cambiar de idioma hay que
   * volver a pintarlas o se quedan en el anterior. */
  var wms = document.getElementById('emodnet-wms');
  if (wms && window.renderWmsLegend) { renderWmsLegend(wms.checked); }
  var dm = document.getElementById('depthmap');
  if (dm && window.renderDepthLegend) { renderDepthLegend(dm.checked); }
}

/* ------------------------------------------------------------ branding */
function applyBrand() {
  var team = BRAND.team || '';
  var el = document.getElementById('brand');
  el.innerHTML = (BRAND.brand || 'Custody') +
    (team ? ' <span class="team">· ' + team.replace(/[<>&]/g, '') + '</span>' : '');
  document.getElementById('tagline').textContent = BRAND.tagline || '';
  document.title = (team ? team + ' · ' : '') + (BRAND.brand || 'Custody');
  if (window.map && map.attributionControl) {
    map.attributionControl.setPrefix(team || BRAND.brand || 'Custody');
  }
}

/* ------------------------------------------------------- gamification */
/* Deliberately cosmetic: it tracks what the reader has looked at, never
 * anything about the data. Nothing here changes a number on screen. */
var ACH = [
  { id: 'first',   k: 'badge_first',   test: function (s) { return s.n >= 1; } },
  { id: 'five',    k: 'badge_five',    test: function (s) { return s.n >= 5; } },
  { id: 'sceptic', k: 'badge_sceptic', test: function (s) { return s.expo >= 1; } },
  { id: 'allind',  k: 'badge_all_ind', test: function (s) { return Object.keys(s.inds).length >= 6; } },
  { id: 'reader',  k: 'badge_reader',  test: function (s) { return !!s.learn; } }
];

function loadSeen() {
  try { return JSON.parse(localStorage.getItem(LS.seen) || '{}'); }
  catch (e) { return {}; }
}
function saveSeen(o) { try { localStorage.setItem(LS.seen, JSON.stringify(o)); } catch (e) {} }

function seenStats() {
  var o = loadSeen(), inds = {}, expo = 0, n = 0;
  Object.keys(o).forEach(function (k) {
    if (k === '_learn') { return; }
    n += 1; inds[k.split('|')[1]] = 1;
    if (o[k] === 'exposure') { expo += 1; }
  });
  return { n: n, expo: expo, inds: inds, learn: !!o._learn };
}

function renderBadges() {
  /* El panel de progreso se retiro: no aportaba nada al operador y ocupaba un
   * boton en la barra. Las insignias siguen contandose para la pestana Learn,
   * pero ya no se pintan en ningun sitio. */
}

window.onAlertInspected = function (p) {
  var o = loadSeen();
  o[p.mmsi + '|' + p.indicator] = p.kind || 'alert';
  saveSeen(o);
  /* SEEN es lo que lee isSeen(); guardarlo solo en localStorage dejaba la
   * marca invisible hasta recargar la pagina, asi que abrir una alerta no
   * la atenuaba ni actualizaba el contador. */
  SEEN = o;
  if (window.renderAlertBar) { renderAlertBar(); }
  if (window.refreshAlertViews) { refreshAlertViews(); }
};

/* ------------------------------------------------------------ Learn tab */
function renderLearn() {
  var box = document.getElementById('learn'); if (!box) { return; }
  var h = '<div class="block note-box"><p>' + t('learn_intro') + '</p></div>';

  h += '<h3>' + t('indicators_h') + '</h3>';
  ['IND-01', 'IND-02', 'IND-03', 'IND-04', 'IND-05', 'IND-06', 'IND-07', 'IND-08'].forEach(function (k) {
    var ex = explainFor(k); if (!ex) { return; }
    h += '<details><summary><span class="badge">' + k + '</span>' + ex.title +
      '</summary><div class="inner"><p>' + ex.what + '</p>' +
      '<p class="note"><b>' + t('why_flagged') + '</b> ' + ex.why + '</p>' +
      '<p class="note"><b>' + t('what_it_means') + ':</b> ' + ex.not + '</p>' +
      '<p class="note">' + ex.tech + '</p></div></details>';
  });

  h += '<h3>' + (LANG === 'es' ? 'Código de color' : 'Colour code') + '</h3>';
  h += '<div class="block note-box"><p>' + t('sev_note') + '</p>' +
    ['extreme', 'severe', 'moderate', 'minor', 'info'].map(function (k) {
      return '<div class="row"><span class="k"><i class="dot" style="display:inline-block;' +
        'width:10px;height:10px;border-radius:50%;background:' + SEVERITY[k].colour +
        ';margin-right:6px"></i>' + (SEVERITY[k].label[LANG] || SEVERITY[k].label.en) +
        '</span><span>' + (k === 'info'
          ? (LANG === 'es' ? 'contexto, no es peligro' : 'context, not a hazard')
          : 'score >= ' + (SEV_BANDS[k] !== undefined ? SEV_BANDS[k] : 0)) +
        '</span></div>'; }).join('') + '</div>';
  h += '<h3>' + t('honest_h') + '</h3>';
  (HONEST[LANG] || HONEST.en).forEach(function (x) {
    h += '<div class="block caution"><p>' + x + '</p></div>';
  });

  h += '<h3>' + t('glossary') + '</h3>';
  (GLOSSARY[LANG] || GLOSSARY.en).forEach(function (row) {
    h += '<details><summary>' + row[0] + '</summary><div class="inner"><p>' +
      row[1] + '</p></div></details>';
  });

  box.innerHTML = h;
}

/* ------------------------------------------------------------ legend */
function renderLegend() {
  var L1 = { en: ['Legend', 'click anything for evidence', 'power cable', 'telecom',
                  'pipeline', 'AIS track', 'alert', 'anchoring ban', 'exposure'],
             es: ['Leyenda', 'clic en cualquier elemento = evidencia', 'cable de potencia',
                  'telecom', 'gasoducto', 'traza AIS', 'alerta', 'prohibición de fondeo',
                  'exposición'] };
  var w = L1[LANG] || L1.en;
  document.getElementById('legend').innerHTML =
    '<div class="panel-head"><b>' + w[0] + '</b>' +
      '<button class="xbtn" data-close="legend" title="hide">&times;</button></div>' +
    '<span class="note">' + w[1] + '</span><br>' +
    '<i style="background:#ff6b6b"></i>' + w[2] + ' &nbsp;' +
    '<i style="background:#4fc3f7"></i>' + w[3] + ' &nbsp;' +
    '<i style="background:#a78bfa"></i>' + w[4] + '<br>' +
    '<i style="background:#3d6a8a"></i>' + w[5] + ' &nbsp;' +
    '<i style="background:#ff4438"></i>' + w[7] + '<br>' +
    '<b style="font-size:10px;letter-spacing:.5px">' +
      (LANG === 'es' ? 'SEVERIDAD · ISO 22324 / CAP' : 'SEVERITY · ISO 22324 / CAP') + '</b><br>' +
    ['extreme', 'severe', 'moderate', 'minor', 'info'].map(function (k) {
      return '<i class="dot" style="background:' + SEVERITY[k].colour + '"></i>' +
        (SEVERITY[k].label[LANG] || SEVERITY[k].label.en); }).join(' &nbsp;') + '<br>' +
    vesselLegend() +
    '<span class="note">Fintraffic/digitraffic.fi CC-BY 4.0 · OSM ODbL · ' +
    'EMODnet Bathymetry DTM · Copernicus Sentinel · Väylävirasto CC-BY 4.0</span>';
}

/* Los marcadores de buque llevaban dos dimensiones de significado sin
 * explicar en ningun sitio: la FORMA dice si el buque emitio rumbo de proa, y
 * el COLOR de que capa y de que instante es. Sin esto el mapa pide adivinar.
 *
 * Los glifos se generan con el mismo shipIcon() que usa el mapa; dibujarlos a
 * mano en la leyenda es la via rapida a que leyenda y mapa dejen de
 * coincidir. */
function vesselGlyph(colour, heading) {
  return '<span class="vg">' + shipIcon(heading, colour, 15).options.html + '</span>';
}

function vesselLegend() {
  /* Solo el VOCABULARIO: forma y color. Los recuentos y que vistas estan
   * encendidas los dice la clave permanente del mapa (mapkey.js), que es la
   * que mira alguien que acaba de abrir la herramienta. Repetirlo aqui
   * garantizaba que los dos textos acabaran diciendo cosas distintas: este
   * todavia afirmaba que solo se dibuja una vista, que ya no es verdad. */
  var V = {
    en: { h: 'VESSELS · shape = heading, colour = which view',
          hdg: 'bow heading broadcast — the arrow is turned to it',
          nohdg: 'no heading in the message (12.6% of fixes) — position only',
          live: 'Live AIS · right now',
          snap: 'At the time cursor · follows the timeline',
          last: 'Last known · frozen at build time',
          dim: 'dim and small = stopped under 0.5 kn, or stale at the cursor' },
    es: { h: 'BUQUES · la forma es el rumbo, el color es la vista',
          hdg: 'emite rumbo de proa — la flecha está girada a él',
          nohdg: 'sin rumbo en el mensaje (12,6% de los fixes) — solo posición',
          live: 'AIS en vivo · ahora mismo',
          snap: 'En el cursor temporal · sigue a la línea temporal',
          last: 'Última conocida · congelada al compilar',
          dim: 'apagado y pequeño = parado bajo 0,5 kn, o viejo en el cursor' } };
  var v = V[LANG] || V.en;
  return '<b style="font-size:10px;letter-spacing:.5px">' + v.h + '</b><br>' +
    vesselGlyph('#5ce1e6', 20) + v.live + '<br>' +
    vesselGlyph('#58d68d', 20) + v.snap + '<br>' +
    vesselGlyph('#7fd7ff', 20) + v.last + '<br>' +
    vesselGlyph('#6a7f91', 20) + v.dim + '<br>' +
    vesselGlyph('#9fb3c4', 20) + v.hdg + '<br>' +
    vesselGlyph('#9fb3c4', null) + v.nohdg + '<br>';
}

/* ------------------------------------------------------------ settings */
function initSettings() {
  var sel = document.getElementById('set-lang');
  sel.innerHTML = Object.keys(STRINGS).map(function (c) {
    return '<option value="' + c + '"' + (c === LANG ? ' selected' : '') + '>' +
      STRINGS[c]._name + '</option>'; }).join('');
  document.getElementById('set-team').value = BRAND.team || '';
  /* El desfase del navegador se ofrece calculado, no escrito a mano: es el
   * unico que el usuario conoce sin pensar. */
  var localMin = -new Date().getTimezoneOffset();
  var tzs = document.getElementById('set-tz');
  tzs.innerHTML =
    '<option value="">' + esc(t('tz_utc')) + '</option>' +
    '<option value="' + localMin + '">' +
      esc(t('tz_local', { o: (localMin < 0 ? '-' : '+') +
        String(Math.floor(Math.abs(localMin) / 60)).padStart(2, '0') + ':' +
        String(Math.abs(localMin) % 60).padStart(2, '0') })) + '</option>' +
    [[120, 'EET · Helsinki, Tallinn, Riga'], [60, 'CET · Berlin, Stockholm, Warsaw'],
     [180, 'MSK · Kaliningrad, St Petersburg']].map(function (z) {
      return '<option value="' + z[0] + '">UTC+' +
        String(z[0] / 60).padStart(2, '0') + ':00 — ' + esc(z[1]) + '</option>';
    }).join('');
  tzs.value = (window.TZ && TZ.offsetMin !== null) ? String(TZ.offsetMin) : '';
  document.getElementById('set-save').addEventListener('click', function () {
    BRAND.team = document.getElementById('set-team').value.trim();
    try { localStorage.setItem(LS.team, BRAND.team); } catch (e) {}
    applyBrand();
    if (window.tzSet) {
      tzSet(tzs.value === '' ? null : +tzs.value);
    }
    setLang(sel.value);
    var m = document.getElementById('set-msg');
    m.textContent = t('saved'); m.className = 'note ok';
    setTimeout(function () { m.textContent = ''; }, 2500);
  });
  document.getElementById('set-reset').addEventListener('click', function () {
    [LS.team, LS.lang, LS.seen, LS.tz, LS.mapkey].forEach(function (k) {
      try { localStorage.removeItem(k); } catch (e) {} });
    location.reload();
  });
}

/* ------------------------------------------------------------ boot */
(function () {
  try {
    var st = localStorage.getItem(LS.lang); if (st && STRINGS[st]) { LANG = st; }
    var tm = localStorage.getItem(LS.team); if (tm !== null) { BRAND.team = tm; }
    var tz = localStorage.getItem(LS.tz);
    if (tz !== null && window.TZ) { TZ.offsetMin = +tz; }
  } catch (e) {}
  SEEN = loadSeen();

  var mk = document.getElementById('tb-mapkey');
  if (mk) { mk.addEventListener('click', function () {
    if (window.mapKeyToggle) { mapKeyToggle(); } }); }
  document.querySelectorAll('[data-toggle]').forEach(function (b) {
    b.addEventListener('click', function () { togglePanel(b.dataset.toggle); }); });
  document.querySelectorAll('[data-close]').forEach(function (b) {
    b.addEventListener('click', function () { togglePanel(b.dataset.close, false); }); });
  applyPanels();

  document.querySelector('#activitybar [data-tab="learn"]').addEventListener('click', function () {
    var o = loadSeen(); if (!o._learn) { o._learn = 1; saveSeen(o); renderBadges(); }
  });

  fetch('config.json').then(function (r) { return r.json(); }).then(function (c) {
    Object.keys(c).forEach(function (k) {
      if (k === 'team' && BRAND.team) { return; }   /* localStorage manda */
      BRAND[k] = c[k];
    });
    try { if (!localStorage.getItem(LS.lang) && STRINGS[c.defaultLang]) {
      LANG = c.defaultLang; } } catch (e) {}
  }).catch(function () { /* config.json es opcional */ })
    .then(function () {
      applyBrand(); applyI18n(); initSettings();
    });
}());
