/* vessel.js - how a vessel is drawn and read.
 *
 * Markers are triangles rotated to the reported heading (falling back to COG),
 * so orientation is readable at a glance. A vessel with neither is drawn as a
 * circle: no arrow is better than an arrow pointing at a guess.
 *
 * The vessel card borrows the layout commercial tools converged on - identity,
 * flag, class, status, then risk - but every field here is either measured or
 * labelled as self-reported. */
'use strict';

var DEPTH = null;   /* rejilla de profundidad, cargada de data/depth_grid.json */

/* Dossier de buques, escrito por build.py (custody/vesselinfo.py). Se declara
 * arriba del todo porque flagOf lo consulta y el orden de ejecucion manda. */
var VINFO = {};
function vinfo(mmsi) { return VINFO[String(mmsi)] || null; }

/* MID -> bandera. Respaldo del Baltico; la tabla completa esta en Python. El
 * resto se muestra como el numero, no como una suposicion. */
var MID = {
  '230': 'Finland', '265': 'Sweden', '266': 'Sweden', '276': 'Estonia',
  '275': 'Latvia', '277': 'Lithuania', '211': 'Germany', '218': 'Germany',
  '219': 'Denmark', '220': 'Denmark', '257': 'Norway', '258': 'Norway',
  '259': 'Norway', '273': 'Russia', '261': 'Poland', '246': 'Netherlands',
  '244': 'Netherlands', '245': 'Netherlands', '235': 'United Kingdom',
  '232': 'United Kingdom', '233': 'United Kingdom', '227': 'France',
  '247': 'Italy', '224': 'Spain', '636': 'Liberia', '538': 'Marshall Islands',
  '352': 'Panama', '353': 'Panama', '354': 'Panama', '370': 'Panama',
  '371': 'Panama', '372': 'Panama', '373': 'Panama', '518': 'Cook Islands',
  '341': 'Saint Kitts and Nevis', '667': 'Sierra Leone', '677': 'Tanzania',
  '355': 'Panama', '563': 'Singapore', '564': 'Singapore', '565': 'Singapore',
  '477': 'Hong Kong', '412': 'China', '413': 'China', '431': 'Japan',
  '440': 'South Korea', '271': 'Turkiye', '304': 'Antigua and Barbuda',
  '305': 'Antigua and Barbuda', '209': 'Cyprus', '210': 'Cyprus', '212': 'Cyprus',
  '248': 'Malta', '249': 'Malta', '256': 'Malta', '215': 'Malta'
};
function flagOf(mmsi) {
  /* El dossier manda: su tabla MID es la lista completa de la UIT y se
   * mantiene en un solo sitio (custody/vesselinfo.py). La tabla de aqui solo
   * cubria el Baltico, asi que banderas de conveniencia que si aparecen en el
   * golfo salian como «MID 255». Queda de respaldo. */
  var vi = (typeof VINFO !== 'undefined') ? VINFO[String(mmsi)] : null;
  if (vi) {
    if (vi.flag) { return vi.flag; }
    if (vi.mmsi_kind && vi.mmsi_kind !== 'ship') { return vi.mmsi_kind; }
  }
  var mid = String(mmsi).slice(0, 3);
  return MID[mid] || ('MID ' + mid);
}

function depthAt(lon, lat) {
  if (!DEPTH) { return null; }
  var i = Math.round((lon - DEPTH.lon0) / DEPTH.step);
  var j = Math.round((lat - DEPTH.lat0) / DEPTH.step);
  if (i < 0 || j < 0 || i >= DEPTH.nx || j >= DEPTH.ny) { return null; }
  var v = DEPTH.vals[j * DEPTH.nx + i];
  return (v === null || v === undefined) ? null : v;
}

/* ------------------------------------------------------- triangle marker */
function shipIcon(headingDeg, color, size, dim) {
  var rot = (headingDeg === null || headingDeg === undefined) ? null : headingDeg;
  var s = size || 18;
  var body = rot === null
    ? '<circle cx="12" cy="12" r="5" fill="' + color + '" stroke="#06101a" stroke-width="1.5"/>'
    : '<path d="M12 2 L19 21 L12 16.5 L5 21 Z" fill="' + color +
      '" stroke="#06101a" stroke-width="1.4" stroke-linejoin="round"/>';
  return L.divIcon({
    className: 'shipmk' + (dim ? ' dim' : ''),
    html: '<svg viewBox="0 0 24 24" width="' + s + '" height="' + s + '"' +
          (rot === null ? '' : ' style="transform:rotate(' + rot + 'deg)"') + '>' +
          body + '</svg>',
    iconSize: [s, s], iconAnchor: [s / 2, s / 2]
  });
}

/* Marcador vectorial sobre el <canvas> compartido de Leaflet: dibuja la misma
 * flecha rotada que shipIcon sin crear >1.000 nodos <svg> en el DOM en cada
 * paso del cursor o sondeo en vivo. Si no hay L.Canvas (tests sin navegador),
 * cae limpiamente a L.marker + shipIcon. */
var ShipCanvasMarker = null;
if (typeof L !== 'undefined' && L.CircleMarker && L.Canvas && L.Canvas.prototype) {
  L.Canvas.prototype._updateShipMarker = function (layer) {
    if (!this._drawing || layer._empty()) { return; }
    var p = layer._point, ctx = this._ctx;
    var rot = layer.options.heading;
    var s = (layer.options.iconSizePx || 17) / 24;
    if (rot === null || rot === undefined || rot >= 360) {
      ctx.beginPath();
      ctx.arc(p.x, p.y, Math.max(Math.round(5 * s), 3), 0, Math.PI * 2, false);
      this._fillStroke(ctx, layer);
      return;
    }
    ctx.save();
    ctx.translate(p.x, p.y);
    ctx.rotate(rot * Math.PI / 180);
    ctx.beginPath();
    ctx.moveTo(0, -10 * s);
    ctx.lineTo(7 * s, 9 * s);
    ctx.lineTo(0, 4.5 * s);
    ctx.lineTo(-7 * s, 9 * s);
    ctx.closePath();
    this._fillStroke(ctx, layer);
    ctx.restore();
  };
  ShipCanvasMarker = L.CircleMarker.extend({
    _updatePath: function () {
      if (this._renderer && this._renderer._updateShipMarker) {
        this._renderer._updateShipMarker(this);
      } else if (this._renderer && this._renderer._updateCircle) {
        this._renderer._updateCircle(this);
      }
    }
  });
}

function createShipMarker(latlng, headingDeg, color, size, dim) {
  var rot = (headingDeg === null || headingDeg === undefined || headingDeg >= 360) ? null : headingDeg;
  var s = size || 18;
  if (ShipCanvasMarker) {
    return new ShipCanvasMarker(latlng, {
      radius: Math.ceil(s / 2) + 2,
      heading: rot,
      iconSizePx: s,
      color: '#06101a',
      weight: 1.4,
      lineJoin: 'round',
      opacity: dim ? 0.5 : 1,
      fill: true,
      fillColor: color,
      fillOpacity: dim ? 0.5 : 0.95
    });
  }
  return L.marker(latlng, { icon: shipIcon(rot, color, s, dim) });
}

function headingOf(p) {
  if (p.heading_deg !== null && p.heading_deg !== undefined && p.heading_deg < 360) {
    return p.heading_deg;
  }
  if (p.heading !== null && p.heading !== undefined && p.heading < 360) { return p.heading; }
  var c = (p.cog_deg !== undefined ? p.cog_deg : p.cog);
  var sog = (p.sog_kn !== undefined ? p.sog_kn : p.sog);
  if (c !== null && c !== undefined && sog > 0.5) { return c; }
  return null;
}

/* ------------------------------------------------------------ situation */
/* "Como se ubica ese barco sobre el agua", en una tabla y sin jerga. */
function situationRows(lon, lat, p) {
  var d = depthAt(lon, lat);
  var hd = headingOf(p);
  var sog = (p.sog_kn !== undefined ? p.sog_kn : p.sog);
  var cog = (p.cog_deg !== undefined ? p.cog_deg : p.cog);
  var hdRaw = (p.heading_deg !== undefined ? p.heading_deg : p.heading);
  var rows = '';
  var row = function (k, v, cls) {
    rows += '<div class="row"><span class="k">' + esc(k) + '</span><span' +
      (cls ? ' class="' + cls + '"' : '') + '>' + v + '</span></div>'; };
  row(t('depth_under'), d === null ? '<span class="note">' + t('no_depth') + '</span>'
      : d.toFixed(0) + ' m');
  row(t('anchor_reach'), d === null ? '-' :
      (d <= 80 ? '<span class="empty">' + t('yes_reach') + '</span>' : t('no_reach')));
  row(t('bow_heading'), (hdRaw === null || hdRaw === undefined || hdRaw >= 360)
      ? '<span class="note">' + t('not_reported') + '</span>' : hdRaw + '°');
  row(t('course_made'), (cog === null || cog === undefined) ? '-' : cog + '°');
  if (hdRaw !== null && hdRaw !== undefined && hdRaw < 360 &&
      cog !== null && cog !== undefined) {
    var dv = ((cog - hdRaw + 540) % 360) - 180;
    row(t('crab_angle'), (dv > 0 ? '+' : '') + dv.toFixed(0) + '° ' +
        (dv > 0 ? t('to_starboard') : t('to_port')),
        Math.abs(dv) > 20 ? 'empty' : '');
  }
  row('SOG', (sog === null || sog === undefined) ? '-' : sog + ' kn');
  row(t('position'), lat.toFixed(4) + ', ' + lon.toFixed(4));
  return rows;
}

/* ------------------------------------------------------- dossier del buque */
/* VINFO lo escribe build.py (custody/vesselinfo.py). Tres niveles, y conviene
 * no confundirlos al leer la ficha:
 *   dimensions  del propio AIS, exacto y sin red (A+B y C+D del mensaje 5)
 *   sanctions   OFAC SDN / lista consolidada de la UE, autoritativo
 *   reference   Wikidata/Commons, parcial y solo de adorno */
var FAMILY_LABEL = {
  cargo: 'Cargo', tanker: 'Tanker', passenger: 'Passenger', fishing: 'Fishing',
  service: 'Service', military: 'Military', sailing: 'Sailing',
  pleasure: 'Pleasure', hsc: 'High-speed craft', wig: 'Wing in ground',
  special: 'Special', other: 'Other', unknown: 'Unknown'
};
var SIZE_LABEL = { small: '< 25 m', coastal: '25-100 m',
                   large: '100-200 m', very_large: '> 200 m' };

function photoUrl(u) {
  /* Dos cosas a la vez:
   *   - miniatura: Special:FilePath admite ?width y el original de ejemplo
   *     pasa de 845 kB a 147 kB. En un popup nadie mira 4000 px.
   *   - por el proxy local si existe: se cachea en disco y, sobre todo, no le
   *     cuenta a Wikimedia qué buque está mirando el operador. */
  if (!u) { return null; }
  var full = u + (u.indexOf('?') < 0 ? '?' : '&') + 'width=640';
  return (window.PROXY && PROXY.on) ? '/cache/img?u=' + encodeURIComponent(full) : full;
}

/* Lo más fuerte de la ficha va arriba y en rojo. Un petrolero sancionado
 * merodeando sobre un cable no es el mismo suceso que un ferry haciendo lo
 * mismo, y enterrar eso en una tabla sería una decisión de diseño con
 * consecuencias. */
function sanctionBanner(vi) {
  if (!vi || !vi.sanctions || !vi.sanctions.length) { return ''; }
  return vi.sanctions.map(function (s) {
    var low = s.confidence === 'low';
    return '<div class="block ' + (low ? 'caution' : 'sanction') + '">' +
      '<h4>' + (low ? '⚠ ' : '⛔ ') + esc(t('sanctioned_h')) + '</h4>' +
      '<div class="row"><span class="k">' + esc(t('sanction_list')) + '</span><span>' +
        esc(s.list) + '</span></div>' +
      (s.programs && s.programs.length
        ? '<div class="row"><span class="k">' + esc(t('sanction_prog')) + '</span><span>' +
          esc(s.programs.join(', ')) + '</span></div>' : '') +
      (s.owner ? '<div class="row"><span class="k">' + esc(t('sanction_owner')) +
        '</span><span>' + esc(s.owner) + '</span></div>' : '') +
      (s.flag ? '<div class="row"><span class="k">' + esc(t('sanction_flag')) +
        '</span><span>' + esc(s.flag) + '</span></div>' : '') +
      '<div class="row"><span class="k">' + esc(t('sanction_match')) + '</span><span>' +
        esc(s.matched_on) + '</span></div>' +
      (s.context ? '<p class="note">' + esc(s.context) + '</p>' : '') +
      '<p class="note">' + esc(t(low ? 'sanction_low' : 'sanction_note')) + '</p></div>';
  }).join('');
}

function dossierBlock(mmsi) {
  var vi = vinfo(mmsi);
  if (!vi) { return ''; }
  var d = vi.dimensions || {}, c = vi.class || {}, r = vi.reference || {};
  var h = sanctionBanner(vi);

  var img = photoUrl(r.image);
  if (img) {
    h += '<div class="block vphoto"><img src="' + esc(img) + '" alt="' +
      esc(vi.name || '') + '" loading="lazy">' +
      '<p class="note">' + esc(r.label || vi.name || '') + ' · ' +
      esc(t('photo_src')) + '</p></div>';
  }

  var rows = '';
  var add = function (k, v, unit) {
    if (v === null || v === undefined || v === '') { return; }
    rows += '<div class="row"><span class="k">' + esc(k) + '</span><span>' +
      esc(v) + (unit ? ' ' + unit : '') + '</span></div>';
  };
  add(t('v_type'), FAMILY_LABEL[c.family] || c.family);
  if (c.type_label && c.type_label !== FAMILY_LABEL[c.family]) {
    add(t('v_subtype'), c.type_label);
  }
  add(t('v_size'), SIZE_LABEL[c.size_class] || c.size_class);
  add(t('v_length'), d.length_m, 'm');
  add(t('v_beam'), d.beam_m, 'm');
  add(t('v_draught'), d.draught_m, 'm');
  add('IMO', vi.imo);
  add(t('v_callsign'), vi.call_sign);
  /* Lo de Wikidata va etiquetado aparte: no es lo mismo una eslora medida por
   * el propio buque que una cifra de una enciclopedia. */
  add(t('v_gt'), r.gross_tonnage);
  add(t('v_dwt'), r.deadweight_t);
  add(t('v_built'), r.built);
  if (rows) {
    h += '<div class="block"><h4>' + esc(t('particulars')) + '</h4>' + rows +
      '<p class="note">' + esc(t('particulars_note')) + '</p>' +
      (r.wikipedia ? '<p class="note"><a href="' + esc(r.wikipedia) +
        '" target="_blank" rel="noopener">Wikipedia</a></p>' : '') + '</div>';
  }
  return h;
}

function vesselCard(mmsi, name, shipType, lon, lat, p) {
  return '<div class="btn-row"><button class="btn primary big js-vessel" data-mmsi="' +
      esc(mmsi) + '">' + esc(t('vessel_situation')) + ' &rarr;</button></div>' +
    dossierBlock(mmsi) +
    '<div class="block"><h4>' + esc(t('identity')) + '</h4>' +
    '<div class="row"><span class="k">' + esc(t('flag')) + '</span><span>' +
      esc(flagOf(mmsi)) + '</span></div>' +
    '<div class="row"><span class="k">' + esc(t('class')) + '</span><span>' +
      esc(shipTypeText(shipType) || t('not_reported')) + '</span></div>' +
    '<div class="row"><span class="k">MMSI</span><span>' + esc(mmsi) + '</span></div>' +
    '<p class="note">' + esc(t('identity_note')) + '</p></div>' +
    '<div class="block"><h4>' + esc(t('situation')) + '</h4>' +
      situationRows(lon, lat, p || {}) + '</div>';
}

/* ------------------------------------------------------------ animation */
/* Estilo Strava / Google Maps: el marcador deja una estela que se dibuja
 * detras, late, y repite en bucle hasta que se oculta. La version anterior
 * era un triangulo discreto que corria una vez y se perdia entre los puntos.
 * El bucle se para solo al cerrar el historial. */
var ANIM = { raf: null, marker: null, trail: null, glow: null, loop: true,
             pts: null, drive: true, lastPush: 0 };

function animMarker(brg) {
  return L.divIcon({
    className: 'animmk',
    html: '<span class="pulse"></span>' +
          '<svg viewBox="0 0 24 24" width="30" height="30"' +
          (brg === null ? '' : ' style="transform:rotate(' + brg + 'deg)"') + '>' +
          '<path d="M12 2 L19 21 L12 16.5 L5 21 Z" fill="#ffe066" ' +
          'stroke="#7a4b00" stroke-width="1.3" stroke-linejoin="round"/></svg>',
    iconSize: [30, 30], iconAnchor: [15, 15]
  });
}

/* La animacion de un buque CONDUCE el reloj global.
 *
 * Antes era un cometa decorativo: interpolaba su propio marcador y no tocaba
 * TIME.cursor, asi que animabas las ultimas 24 h de un barco y el resto del
 * mapa se quedaba congelado en otro instante. Dos relojes contradiciendose.
 *
 * Ahora hay uno. El cometa marca el buque que se esta estudiando y, en el
 * mismo paso, empuja el cursor global, asi que TODO el mapa se mueve con el.
 * El empuje va frenado: el cometa corre a 60 fps y redibujar la instantanea
 * son ~1.300 marcadores, que a esa cadencia haria la animacion inutil. */
var ANIM_PUSH_MS = 250;

function animateTrack(pts, ms, loop) {
  stopAnim();
  if (!pts || pts.length < 2) { return; }
  ANIM.pts = pts;
  ANIM.loop = (loop === undefined) ? true : !!loop;
  /* Un solo reloj: si la linea temporal estaba reproduciendo, se para. */
  if (window.stopPlay) { stopPlay(); }
  /* Y se desengancha el vivo, o el siguiente sondeo tiraria del cursor al
   * presente a mitad de la reproduccion. */
  if (typeof LIVE !== 'undefined' && LIVE.on) { LIVE.follow = false; }
  ANIM.lastPush = 0;
  var dur = ms || 4000;
  var t0 = pts[0].t, t1 = pts[pts.length - 1].t;
  var span = Math.max(1, t1 - t0);

  ANIM.trail = L.polyline([], { color: '#ffe066', weight: 5, opacity: 0.95,
                                lineCap: 'round', lineJoin: 'round' }).addTo(map);
  ANIM.glow = L.polyline([], { color: '#fff3bf', weight: 11, opacity: 0.18,
                               lineCap: 'round' }).addTo(map);
  ANIM.marker = L.marker([pts[0].lat, pts[0].lon],
    { icon: animMarker(null), zIndexOffset: 1200, interactive: false }).addTo(map);

  var start = null;
  var step = function (now) {
    if (start === null) { start = now; }
    var f = Math.min(1, (now - start) / dur);
    var want = t0 + f * span;
    var i = 0;
    while (i < pts.length - 2 && pts[i + 1].t < want) { i += 1; }
    var a = pts[i], b = pts[i + 1] || a;
    var g = (b.t === a.t) ? 0 : (want - a.t) / (b.t - a.t);
    var la = a.lat + (b.lat - a.lat) * g, lo = a.lon + (b.lon - a.lon) * g;

    /* estela: los puntos ya recorridos mas la posicion interpolada */
    var done = pts.slice(0, i + 1).map(function (x) { return [x.lat, x.lon]; });
    done.push([la, lo]);
    /* solo los ultimos 40 vertices, para que sea cometa y no traza completa */
    var tail = done.slice(Math.max(0, done.length - 40));
    ANIM.trail.setLatLngs(tail);
    ANIM.glow.setLatLngs(tail);
    ANIM.marker.setLatLng([la, lo]);
    ANIM.marker.setIcon(animMarker(bearing(a.lat, a.lon, b.lat, b.lon)));

    /* El reloj global sigue al cometa, frenado. */
    if (ANIM.drive && window.setCursor && (now - ANIM.lastPush) > ANIM_PUSH_MS) {
      ANIM.lastPush = now;
      setCursor(want, true);
    }

    if (f < 1) { ANIM.raf = requestAnimationFrame(step); }
    else if (ANIM.loop) { start = null; ANIM.raf = requestAnimationFrame(step); }
    else if (window.setCursor) { setCursor(t1, false); }
  };
  ANIM.raf = requestAnimationFrame(step);
}

function stopAnim() {
  if (ANIM.raf) { cancelAnimationFrame(ANIM.raf); ANIM.raf = null; }
  ['marker', 'trail', 'glow'].forEach(function (k) {
    if (ANIM[k]) { map.removeLayer(ANIM[k]); ANIM[k] = null; }
  });
}

function bearing(la1, lo1, la2, lo2) {
  var r = Math.PI / 180;
  var y = Math.sin((lo2 - lo1) * r) * Math.cos(la2 * r);
  var x = Math.cos(la1 * r) * Math.sin(la2 * r) -
          Math.sin(la1 * r) * Math.cos(la2 * r) * Math.cos((lo2 - lo1) * r);
  return (Math.atan2(y, x) / r + 360) % 360;
}

function loadDepth() {
  return fetch('data/depth_grid.json').then(function (r) { return r.json(); })
    .then(function (d) { DEPTH = d; }).catch(function () { DEPTH = null; });
}

/* ------------------------------------------------- popup compacto */
/* UX: un popup es contexto transitorio. Aqui solo va lo que identifica al
 * objeto y las dos acciones; el resto al panel lateral, que tiene scroll.
 * Antes el popup llevaba la tabla entera y se salia de la pantalla. */
function originDest(mmsi, p) {
  var dest = p.destination || null;
  var first = null;
  var h = (typeof HIST !== 'undefined') && HIST[String(mmsi)];
  if (h && h.pts && h.pts.length) { first = h.pts[0]; }
  var rows = '';
  rows += '<div class="row"><span class="k">' + esc(t('from_first_seen')) +
    '</span><span>' + (first ? fmtUTC(first.t).slice(0, 16) : '-') + '</span></div>';
  rows += '<div class="row"><span class="k">' + esc(t('to_destination')) +
    '</span><span>' + (dest ? esc(dest) : '<span class="note">' +
      esc(t('not_reported')) + '</span>') + '</span></div>';
  return rows;
}

/* La accion principal va ARRIBA. Estaba al final del popup, despues de la
 * tabla de situacion, y habia que leerse la ficha entera para encontrarla.
 * Un popup es una pregunta («¿que es esto?») con una respuesta corta y una
 * salida; la salida no puede estar escondida. */
function vesselPopupCompact(p, coords) {
  var name = p.name || ('MMSI ' + p.mmsi);
  return '<h4>' + esc(name) + '</h4>' +
    '<div class="btn-row"><button class="btn primary big js-vessel" data-mmsi="' +
      esc(p.mmsi) + '">' + esc(t('vessel_situation')) + ' &rarr;</button></div>' +
    '<div class="note">' + esc(flagOf(p.mmsi)) + ' · ' +
      esc(shipTypeText(p.ship_type) || t('not_reported')) + '</div>' +
    originDest(p.mmsi, p) +
    '<div class="btn-row">' +
      '<button class="btn js-track" data-mmsi="' + esc(p.mmsi) + '">' +
        esc(t('show_history')) + '</button>' +
    '</div>';
}
