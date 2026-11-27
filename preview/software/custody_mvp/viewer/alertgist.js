/* alertgist.js - el POR QUE de una alerta concreta, en numeros.
 *
 * explain.js dice que es un IND-04 en general. Esto dice que paso en ESTE
 * caso: cuanto duro el hueco, cuantos grados se desvio, a que distancia del
 * cable. Son los campos que el detector ya guardo en `evidence` al emitirla,
 * no una relectura ni una estimacion.
 *
 * Existe porque al abrir «Vessel situation» desde una alerta se perdia la
 * alerta: el panel mostraba el buque y no lo que se le reprochaba. Esto es lo
 * que se promociona al principio del panel, pegado al selector de rango, que
 * es el primer sitio donde se mira.
 *
 * Cada entrada declara `needs`: el bloque del panel del buque que contiene la
 * prueba. Ese bloque se abre solo. Si el buque dejo de reportar, lo que hay
 * que ver son los huecos; si dio un salto imposible, las posiciones.
 */
'use strict';

function _n(x, d) {
  if (x === null || x === undefined) { return null; }
  return Number(x).toFixed(d === undefined ? 1 : d).replace(/\.0$/, '');
}

/* Cada funcion devuelve filas [etiqueta, valor]. Valor ya formateado: la
 * unidad forma parte del dato y separarla solo invita a perderla. */
var GIST = {
  'IND-01': function (e) {
    return { needs: 'positions', rows: [
      [t('g_speed_held'), _n(e.sog_median_kn) + ' kn (p10 ' + _n(e.sog_p10_kn) +
        ' – p90 ' + _n(e.sog_p90_kn) + ')'],
      [t('g_for'), fmtDur((e.duration_s || 0) * 1000)],
      [t('g_corridor_dist'), e.min_distance_m !== undefined && e.min_distance_m !== null
        ? Math.round(e.min_distance_m) + ' m' : (e.within_500m_buffer ? '< 500 m' : null)],
      [t('g_depth'), e.depth_m !== null && e.depth_m !== undefined ? _n(e.depth_m) + ' m' : null]
    ] };
  },
  'IND-02': function (e) {
    /* bias_sign llega del detector en castellano («estribor»/«babor»); se
     * traduce aqui y no en el build para no tocar el dato emitido. */
    var side = e.bias_sign === 'estribor' ? t('g_starboard')
             : e.bias_sign === 'babor' ? t('g_port') : e.bias_sign;
    return { needs: 'positions', rows: [
      [t('g_bias'), _n(e.bias_abs_median_deg) + '° ' + t('g_to') + ' ' + side],
      [t('g_consistency'), e.sign_consistency !== undefined
        ? Math.round(e.sign_consistency * 100) + '% ' + t('g_same_side') : null],
      [t('g_samples'), e.samples ? e.samples + ' ' + t('g_fixes') : null],
      [t('g_for'), fmtDur((e.duration_s || 0) * 1000)]
    ] };
  },
  'IND-03': function (e) {
    return { needs: 'positions', rows: [
      [t('g_moved'), _n(e.net_displacement_nm, 2) + ' NM ' + t('g_net')],
      [t('g_max_speed'), _n(e.sog_max_kn) + ' kn'],
      [t('g_for'), fmtDur((e.duration_s || 0) * 1000)]
    ] };
  },
  'IND-04': function (e) {
    return { needs: 'gaps', rows: [
      [t('g_silent_for'), fmtDur((e.gap_s || 0) * 1000)],
      [t('g_last_heard'), e.t_start_ms ? fmtUTC(e.t_start_ms) : null],
      [t('g_came_back'), e.gap_state === 'open' ? t('g_still_silent')
        : (e.t_end_ms ? fmtUTC(e.t_end_ms) : null)],
      [t('g_moved_meanwhile'), e.jump_nm !== undefined && e.jump_nm !== null
        ? _n(e.jump_nm, 1) + ' NM' : null]
    ] };
  },
  'IND-05': function (e) {
    return { needs: 'positions', rows: [
      [t('g_cable'), e.corridor ? e.corridor +
        (e.corridor_class ? ' (' + e.corridor_class + ')' : '') : null],
      [t('g_passed_within'), e.min_distance_m !== null && e.min_distance_m !== undefined
        ? Math.round(e.min_distance_m) + ' m' : null],
      [t('g_depth'), e.depth_m !== null && e.depth_m !== undefined ? _n(e.depth_m) + ' m' : null],
      [t('g_anchor_reach'), e.anchor_feasible === true ? t('g_yes_reach')
        : e.anchor_feasible === false ? t('g_no_reach') : null]
    ] };
  },
  'IND-06': function (e) {
    return { needs: 'positions', rows: [
      [t('g_partner'), e.partner_name
        ? e.partner_name + ' · MMSI ' + e.partner_mmsi : ('MMSI ' + e.partner_mmsi)],
      [t('g_closest'), Math.round(e.min_distance_m) + ' m'],
      [t('g_for'), fmtDur((e.duration_s || 0) * 1000)],
      [t('g_samples'), e.samples ? e.samples + ' ' + t('g_fixes') : null]
    ] };
  },
  'IND-07': function (e) {
    /* La clase va PRIMERA. «279 kn implicitos» sin decir que es un MMSI
     * compartido invita a leer un incidente donde hay un remolcador con la
     * matricula duplicada. */
    var k = e.jump_kind;
    return { needs: 'gaps', rows: [
      [t('g_jump_kind'), k ? t('jk_' + k) : null],
      [t('g_implied'), _n(e.implied_speed_kn, 0) + ' kn'],
      [t('g_reported'), e.reported_sog_kn !== null && e.reported_sog_kn !== undefined
        ? _n(e.reported_sog_kn) + ' kn' : null],
      [t('g_jumped'), _n(e.jump_distance_km, 1) + ' km ' + t('g_in') + ' ' +
        fmtDur((e.elapsed_s || 0) * 1000)],
      [t('g_jumps_total'), e.jumps_in_track ? e.jumps_in_track + ' ' + t('g_in_track') : null]
    ] };
  }
};

/* Devuelve null si no se reconoce el indicador: mejor no pintar el bloque que
 * pintarlo vacio. */
function alertGist(p) {
  if (!p || !p.indicator || !GIST[p.indicator]) { return null; }
  var e = p.evidence || {};
  var g;
  try { g = GIST[p.indicator](e); } catch (err) { return null; }
  var rows = g.rows.filter(function (r) {
    return r[1] !== null && r[1] !== undefined && String(r[1]).indexOf('null') < 0;
  });
  if (!rows.length) { return null; }
  var ex = window.explainFor ? explainFor(p.indicator) : null;
  return { title: ex ? ex.title : p.indicator, rows: rows, needs: g.needs,
           t0: e.t_start_ms || p.ts_ms, t1: e.t_end_ms || p.ts_ms };
}
