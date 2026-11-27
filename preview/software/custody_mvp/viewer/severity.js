/* severity.js - colour and ordering of alerts.
 *
 * Standards used, both citable in a pitch:
 *   ISO 22324:2022 (Security and resilience - Emergency management -
 *   Guidelines for colour-coded alerts): red = danger, act now; yellow =
 *   caution, prepare; green = safe, no action. Supplementary blue/grey/purple
 *   allowed for information that is not a hazard level. Never more than seven
 *   levels.
 *
 *   CAP (OASIS Common Alerting Protocol) severity vocabulary, with the
 *   colour mapping harmonised by EUMETNET Meteoalarm across EU states:
 *   Extreme=red, Severe=orange, Moderate=yellow, Minor=green.
 *
 * Exposures are NOT a hazard level. They are context, so they take the
 * supplementary blue, not a point on the red-green spectrum. Painting them
 * yellow would claim a caution we cannot justify. */
'use strict';

var SEVERITY = {
  extreme:  { rank: 4, colour: '#e02b20', ring: '#ff6b60', label: { en: 'Extreme', es: 'Extrema' } },
  severe:   { rank: 3, colour: '#f07318', ring: '#ffa05a', label: { en: 'Severe',  es: 'Severa'  } },
  moderate: { rank: 2, colour: '#f2c230', ring: '#ffe07a', label: { en: 'Moderate', es: 'Moderada' } },
  minor:    { rank: 1, colour: '#4caf6d', ring: '#8fe6a8', label: { en: 'Minor',   es: 'Menor'   } },
  info:     { rank: 0, colour: '#3f8fd0', ring: '#86c5f0', label: { en: 'Context', es: 'Contexto' } }
};

/* Exposures -> info. Alerts -> CAP band from the composite score.
 *
 * Las bandas estan calibradas sobre la distribucion REAL de este almacen, no
 * sobre 0.25/0.50/0.75 teoricos: medido sobre 62 alertas, el maximo observado
 * es 0.317 y la mediana 0.095, asi que una escala a 0.75 pintaba el 97 % de
 * verde y no discriminaba nada. Son cuantiles aproximados (p50/p75/p90) y
 * siguen siendo provisionales: cambiaran cuando haya semanas de datos, y el
 * numero vive en un solo sitio para poder recalibrarlo. */
var SEV_BANDS = { extreme: 0.145, severe: 0.115, moderate: 0.070 };

function severityOf(p) {
  if (p.kind === 'exposure') { return 'info'; }
  var s = (p.composite_score !== undefined && p.composite_score !== null)
    ? p.composite_score : (p.score || 0);
  if (s >= SEV_BANDS.extreme) { return 'extreme'; }
  if (s >= SEV_BANDS.severe) { return 'severe'; }
  if (s >= SEV_BANDS.moderate) { return 'moderate'; }
  return 'minor';
}
function sevColour(p) { return SEVERITY[severityOf(p)].colour; }
function sevRing(p) { return SEVERITY[severityOf(p)].ring; }
function sevLabel(p) {
  var L = SEVERITY[severityOf(p)].label;
  return L[LANG] || L.en;
}

/* ------------------------------------------------------------- ordering */
var SORTS = {
  severity: function (a, b) {
    var d = SEVERITY[severityOf(b.properties)].rank - SEVERITY[severityOf(a.properties)].rank;
    return d || (b.properties.composite_score || 0) - (a.properties.composite_score || 0);
  },
  recent: function (a, b) { return (b.properties.ts_ms || 0) - (a.properties.ts_ms || 0); },
  score: function (a, b) {
    return (b.properties.composite_score || 0) - (a.properties.composite_score || 0); },
  distance: function (a, b) {
    var da = (a.properties.evidence || {}).min_distance_m;
    var db = (b.properties.evidence || {}).min_distance_m;
    if (da === undefined && db === undefined) { return 0; }
    if (da === undefined) { return 1; }
    if (db === undefined) { return -1; }
    return da - db;
  },
  indicator: function (a, b) {
    return String(a.properties.indicator).localeCompare(String(b.properties.indicator)); }
};
var SORT_KEYS = ['severity', 'recent', 'score', 'distance', 'indicator'];
var CURRENT_SORT = 'severity';

function sortAlerts(feats) {
  return feats.slice().sort(SORTS[CURRENT_SORT] || SORTS.severity);
}
