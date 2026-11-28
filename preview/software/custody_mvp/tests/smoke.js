/* smoke.js - carga los scripts del visor en el mismo orden que index.html, con
 * un DOM y un Leaflet minimos, y falla si algo revienta al arrancar.
 * No sustituye a un navegador: atrapa ReferenceError por orden de carga y
 * errores de sintaxis, que es lo que se nos ha colado dos veces.
 *   uso: node smoke.js
 */
'use strict';

/* Los tests viven en tests/ y el visor en viewer/. Esto se ejecuta desde la
 * raiz del proyecto (tests/run.sh), asi que se entra en viewer/ una sola vez
 * en lugar de prefijar cada ruta del fichero. */
process.chdir(require('path').join(__dirname, '..', 'viewer'));
/* `data/` ya no vive dentro de viewer/: la ruta la fija config/custody.toml.
 * Se pregunta por ella en vez de suponerla, y si no esta se para -- una
 * bateria que pasa porque no encontro datos es peor que ninguna. */
const DATA = require('child_process').execSync(
  'python3 -c "from custody import paths; print(paths.data())"',
  { cwd: require('path').join(__dirname, '..'), encoding: 'utf8' }).trim();
if (!require('fs').existsSync(require('path').join(DATA, 'manifest.json'))) {
  console.log('FALLO no hay build en ' + DATA + ' -- nada que comprobar');
  process.exit(1);
}
const fs = require('fs'), vm = require('vm'), path = require('path');

const order = String(fs.readFileSync('index.html'))
  .split('\n').filter(l => l.includes('<script src='))
  .map(l => l.match(/src="([^"]+)"/)[1])
  .filter(f => !f.includes('vendor/'));

const DOM = {};
const el = () => new Proxy({
  style: {}, dataset: {}, classList: { add(){}, remove(){}, toggle(){}, contains(){return false} },
  addEventListener(){}, appendChild(){}, setAttribute(){}, focus(){}, setSelectionRange(){},
  querySelectorAll(){ return [] }, querySelector(){ return el() },
  innerHTML: '', textContent: '', value: '', checked: false, disabled: false, selectionStart: 0
}, { get: (t, k) => (k in t ? t[k] : el()), set: (t, k, v) => (t[k] = v, true) });

/* addTo(map) REGISTRA la capa en el mapa y se devuelve a si misma, como hace
 * Leaflet. Antes devolvia un stub nuevo y no avisaba al mapa, asi que nada
 * podia comprobarse sobre que hay dibujado. */
const layerStub = () => {
  const self = new Proxy({
    addTo(m){ if (m && m.addLayer) { m.addLayer(self); } return self; },
    bindPopup(){ return self }, on(){}, off(){},
    eachLayer(){}, bringToFront(){}, bringToBack(){}, setLatLng(){}, setIcon(){},
    getElement(){ return el() }, setContent(){ return self }, openOn(){},
    setLatLngs(){}, getBounds(){ return {} }
  }, { get: (t, k) => (k in t ? t[k] : layerStub.bind(null)) });
  return self;
};

const L = {
  map: () => layerStub(), tileLayer: Object.assign(() => layerStub(), { wms: () => layerStub() }),
  geoJSON: () => layerStub(), layerGroup: () => layerStub(), marker: () => layerStub(),
  circleMarker: () => layerStub(), circle: () => layerStub(), polyline: () => layerStub(),
  popup: () => layerStub(), divIcon: o => ({ options: o }), latLngBounds: () => ({}), control: Object.assign(() => layerStub(), { scale: () => layerStub(), layers: () => layerStub() })
};
/* El mapa falso LLEVA LA CUENTA de lo que tiene encima. Antes hasLayer()
 * devolvia false siempre, asi que cualquier comprobacion sobre que se esta
 * dibujando pasaba en vacio: decia «ok» sin mirar nada. */
L.map = () => {
  const on = new Set();
  return Object.assign(layerStub(), {
    fitBounds(){}, setView(){}, getBoundsZoom(){ return 8 },
    addLayer(l){ on.add(l); return this; },
    removeLayer(l){ on.delete(l); return this; },
    hasLayer(l){ return on.has(l); },
    closePopup(){}, on(){}, attributionControl: { setPrefix(){} }
  });
};

const ctx = {
  console, setInterval: () => 0, clearInterval(){}, setTimeout: () => 0,
  requestAnimationFrame: () => 0, cancelAnimationFrame(){}, performance: { now: () => 0 },
  Date, Math, JSON, Object, Array, String, Number, Boolean, Error, RegExp, isNaN, parseInt,
  parseFloat, encodeURIComponent, decodeURIComponent, localStorage: { getItem: () => null, setItem(){}, removeItem(){} },
  location: { hash: '', href: '' }, history: { replaceState(){} },
  fetch: () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) }),
  /* UN NODO POR ID, no uno nuevo en cada llamada.
   *
   * `getElementById: () => el()` devolvia un doble distinto cada vez, asi que
   * escribir innerHTML en uno no se veia desde otra busqueda del mismo id --
   * y cualquier comprobacion sobre lo que un panel PINTA salia vacia. Un
   * navegador devuelve el mismo nodo; el doble ahora tambien. */
  document: { documentElement: el(), title: '',
              getElementById: (id) => (DOM[id] || (DOM[id] = el())),
              querySelector: () => el(), querySelectorAll: () => [], createElement: () => el(),
              addEventListener(){}, removeEventListener(){},
              body: el() },
  getComputedStyle: () => ({ getPropertyValue: () => '54px' }),
  L
};
ctx.addEventListener = () => {};
ctx.window = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);

let bad = 0;
for (const f of order) {
  try {
    vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, { filename: f });
    console.log('  ok    ' + f);
  } catch (e) {
    bad += 1;
    console.log('  FALLO ' + f + '  -> ' + e.name + ': ' + e.message);
  }
}
/* Claves de traduccion referenciadas y no definidas. Un t('x') inexistente no
 * lanza: devuelve la clave cruda y aparece en pantalla como texto feo. */
if (ctx.STRINGS) {
  const used = new Set();
  for (const f of order) {
    const src = fs.readFileSync(f, 'utf8');
    /* El cierre con , o ) descarta las claves compuestas t('sort_' + k) */
    for (const m of src.matchAll(/\bt\('([a-z0-9_]+)'\s*[,)]/g)) { used.add(m[1]); }
  }
  for (const m of String(fs.readFileSync('index.html')).matchAll(/data-i18n="([^"]+)"/g)) {
    used.add(m[1]);
  }
  for (const lang of Object.keys(ctx.STRINGS)) {
    const miss = [...used].filter(k => !(k in ctx.STRINGS[lang]));
    if (miss.length) { bad += 1; console.log('  FALTA i18n [' + lang + ']: ' + miss.join(', ')); }
  }
  /* Claves repetidas dentro de un mismo diccionario. Comparar los CONJUNTOS
   * de claves no las ve, porque la ultima gana y el conjunto sale igual: el
   * diccionario `es` llevaba dos bloques en ingles pegados por error, tapados
   * por las traducciones de mas abajo. Quien editara la primera copia no
   * habria visto ningun efecto. */
  const src = String(fs.readFileSync('i18n.js'));
  for (const lang of Object.keys(ctx.STRINGS)) {
    const i = src.indexOf('\n  ' + lang + ': {');
    let d = 0, j = src.indexOf('{', i), body = '';
    for (let k = j; k < src.length; k += 1) {
      if (src[k] === '{') { d += 1; } else if (src[k] === '}') {
        d -= 1; if (!d) { body = src.slice(j, k); break; } }
    }
    const ks = [...body.matchAll(/(?:^|[,{])\s*([a-z0-9_]+):/g)].map(m => m[1]);
    const dup = [...new Set(ks.filter((k, n) => ks.indexOf(k) !== n))];
    if (dup.length) {
      bad += 1;
      console.log('  FALLO i18n [' + lang + '] claves repetidas: ' + dup.join(', '));
    }
  }
  /* Y traducciones que son literalmente el ingles. Unas pocas lo son con
   * razon (nombres propios, «fixes», «cable»); mas que eso es un olvido. */
  const same = Object.keys(ctx.STRINGS.en)
    .filter(k => ctx.STRINGS.es[k] === ctx.STRINGS.en[k]);
  if (same.length > 8) {
    bad += 1;
    console.log('  FALLO i18n: ' + same.length + ' claves sin traducir: ' + same.join(', '));
  } else {
    console.log('  ok    i18n (' + Object.keys(ctx.STRINGS.en).length
                + ' claves, sin repetidas, ' + same.length + ' iguales en los dos idiomas)');
  }
}

/* Arranque real con los datos del ultimo build: pinta lo que pinta el visor
 * y falla si alguna de esas funciones revienta. Es lo que la carga limpia no
 * cubre, porque los fallos de render ocurren despues del parseo. */
const rd = n => { const p = path.join(DATA, n);
  return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : null; };
const manifest = rd('manifest.json');
if (manifest) {
  ctx.manifest = manifest;
  const stage = [
    ['addTracks', rd('tracks.geojson')],
    ['addAlerts', rd('alerts.geojson')],
    ['addSuppressed', rd('suppressed.geojson')],
    ['addGfw', rd('gfw_events.geojson')],
    ['addGfwGrid', rd('gfw_grid.geojson')],
    ['addWrecks', rd('wrecks.geojson')],
    ['addMilitary', rd('military_areas.geojson')],
    ['addMunitions', rd('munitions.geojson')],
    ['renderHealth', undefined],
    ['renderOpsFilters', undefined],
    ['renderSources', undefined],
    ['renderSourceStrip', undefined],
    ['renderLayers', undefined]
  ];
  /* positions y snapshot hacen falta montadas: sin ellas la comprobacion de
   * exclusividad de abajo pasaria sin comprobar nada. */
  /* positionsFc antes de construir el historial: de ahi salen los buques de
   * un solo avistamiento que se siembran en HIST. */
  ctx.positionsFc = rd('positions.geojson');
  /* Las subcuencas HELCOM: sin ellas BASINS esta vacio y todo lo que
   * clasifica por cuenca mide cero. */
  if (typeof ctx.loadBasins === 'function') { ctx.loadBasins(rd('basins.geojson')); }
  /* El visor fija TIME.t0/t1 en initTime(), que aqui no corre. Se derivan una
   * sola vez y en el montaje: cuando esto vivia dentro de una comprobacion,
   * las que corrian antes se encontraban t0=t1=0 y median cualquier cosa. */
  if (typeof ctx.buildHistory === 'function') {
    ctx.buildHistory(rd('tracks.geojson'));
    let lo = Infinity, hi = 0;
    Object.keys(ctx.HIST).forEach(k => {
      const pts = ctx.HIST[k].pts;
      lo = Math.min(lo, pts[0].t); hi = Math.max(hi, pts[pts.length - 1].t);
    });
    ctx.TIME.t0 = lo; ctx.TIME.t1 = hi;
    ctx.applyView();
  }
  for (const [fn, arg] of stage) {
    if (typeof ctx[fn] !== 'function') { bad += 1; console.log('  FALTA función: ' + fn); continue; }
    if (arg === null) { console.log('  --    ' + fn + ' (sin fichero)'); continue; }
    try { ctx[fn](arg); console.log('  ok    ' + fn + '()'); }
    catch (e) { bad += 1; console.log('  FALLO ' + fn + '() -> ' + e.name + ': ' + e.message); }
  }
  /* Dossier de buques: se carga aparte de las capas GeoJSON, asi que hay que
   * montarlo a mano y comprobar que la ficha y las facetas se pintan. */
  try {
    const vi = rd('vessel_info.json');
    if (vi && typeof ctx.renderVesselTab === 'function') {
      ctx.VINFO = vi;
      const tracks = rd('tracks.geojson');
      if (tracks) { ctx.buildHistory(tracks); }
      ctx.renderVesselTab('');
      const san = Object.values(vi).filter(r => r.sanctions && r.sanctions.length);
      const withPic = Object.values(vi).filter(r => (r.reference || {}).image);
      const card = ctx.vesselCard(san.length ? san[0].mmsi : Object.keys(vi)[0],
                                  null, 80, 24.5, 59.9, {});
      if (san.length && card.indexOf('sanction') < 0) {
        bad += 1; console.log('  FALLO la ficha de un buque sancionado no muestra el aviso');
      } else {
        console.log('  ok    renderVesselTab() · dossier (' + Object.keys(vi).length +
          ' buques, ' + san.length + ' sancionados, ' + withPic.length + ' con foto)');
      }
      /* Las facetas de clasificacion son logica pura: se comprueban. */
      const n0 = ctx.vesselList('').length;
      ctx.VFILTER.sanctioned = true;
      const n1 = ctx.vesselList('').length;
      ctx.VFILTER.sanctioned = false;
      if (!(n0 > 0 && n1 < n0)) {
        bad += 1; console.log('  FALLO filtro de clasificacion: ' + n0 + ' -> ' + n1);
      } else { console.log('  ok    facetas de clasificacion (' + n0 + ' -> ' + n1 +
        ' solo sancionados)'); }
    }
  } catch (e) { bad += 1; console.log('  FALLO dossier -> ' + e.name + ': ' + e.message); }

  /* Contexto del fondo: lo valioso no es la capa sino la anotacion en la
   * alerta. Si deja de escribirse, el visor pierde el unico dato que explica
   * por que un buque de guerra lento no es una anomalia. */
  try {
    const al = rd('alerts.geojson');
    if (al) {
      const ann = al.features.filter(f => (f.properties.evidence || {}).military_area);
      const wr = al.features.filter(f => (f.properties.evidence || {}).nearest_wreck);
      const has = al.features.filter(f => 'military_area' in (f.properties.evidence || {}));
      if (!has.length) {
        bad += 1; console.log('  FALLO ninguna alerta lleva contexto de fondo');
      } else {
        console.log('  ok    contexto de fondo en alertas (' + ann.length +
          ' en area de defensa, ' + wr.length + ' cerca de un pecio, de ' +
          has.length + ' anotadas)');
      }
    }
  } catch (e) { bad += 1; console.log('  FALLO contexto de fondo -> ' + e.message); }

  /* La justificacion de un area de defensa es el punto del ejercicio: si el
   * popup deja de decir QUE hay dentro, la capa vuelve a ser un poligono azul
   * sin explicar. */
  try {
    const mil = rd('military_areas.geojson');
    if (mil && mil.features && mil.features.length && typeof ctx.milWhy === 'function') {
      const withWhy = mil.features.filter(f => (f.properties.why || {}).corridors);
      if (!withWhy.length) {
        bad += 1; console.log('  FALLO ningun area de defensa lista la infraestructura que contiene');
      } else {
        const html = ctx.milWhy(withWhy[0].properties);
        const names = withWhy[0].properties.why.corridors.map(c => c.name);
        const ok = names.every(n => html.indexOf(n) >= 0);
        const gap = withWhy.filter(f => (f.properties.why || {}).anchoring_bans_inside === 0);
        if (!ok) { bad += 1; console.log('  FALLO milWhy no pinta los corredores'); }
        else {
          console.log('  ok    justificacion de areas (' + withWhy.length + '/' +
            mil.features.length + ' con corredor dentro, ' + gap.length +
            ' de esas sin prohibicion de fondeo)');
        }
      }
    } else {
      console.log('  --    justificacion de areas (sin datos en --skip-net)');
    }
  } catch (e) { bad += 1; console.log('  FALLO justificacion de areas -> ' + e.message); }

  /* Resolucion de destinos: si la tabla se rompe, la proyeccion de ruta
   * apunta a ninguna parte o, peor, a un sitio equivocado en silencio. */
  try {
    if (typeof ctx.resolveDestination === 'function') {
      const tr = rd('tracks.geojson');
      const cases = [['FIHEL', 'exact'], ['RU LED', 'exact'], ['HELSINKI', 'exact'],
                     ['FIHEL VIA NOK', 'prefix'], ['FOR ORDER', 'not-a-destination'],
                     ['ZZQQQ', 'unresolved']];
      const wrong = cases.filter(c => ctx.resolveDestination(c[0]).via !== c[1]);
      if (wrong.length) {
        bad += 1;
        console.log('  FALLO resolveDestination: ' + wrong.map(c =>
          c[0] + ' -> ' + ctx.resolveDestination(c[0]).via + ' (esperado ' + c[1] + ')').join(', '));
      } else if (tr) {
        const res = tr.features.filter(f =>
          (ctx.resolveDestination(f.properties.destination) || {}).port).length;
        const pct = Math.round(100 * res / tr.features.length);
        if (pct < 35) {
          bad += 1; console.log('  FALLO cobertura de destinos cayo al ' + pct + '%');
        } else {
          console.log('  ok    destinos (' + ctx.PORTS.length + ' puertos, resuelve ' +
            res + '/' + tr.features.length + ' = ' + pct + '%)');
        }
      }
    }
  } catch (e) { bad += 1; console.log('  FALLO destinos -> ' + e.message); }

  /* El AOI del visor tiene que salir del manifest, no estar a fuego. Lo
   * estuvo, y el modo en vivo filtraba al golfo con un build del Baltico:
   * 543 buques en pantalla de los 1.070 que llegaban. */
  try {
    if (typeof ctx.setAoi === 'function' && manifest.aoi) {
      ctx.setAoi(manifest.aoi);
      const a = ctx.AOI, m2 = manifest.aoi;
      const ok = a[0][1] === m2[0] && a[0][0] === m2[1] &&
                 a[1][1] === m2[2] && a[1][0] === m2[3];
      if (!ok) {
        bad += 1; console.log('  FALLO AOI del visor no coincide con el manifest: ' +
          JSON.stringify(a) + ' vs ' + JSON.stringify(m2));
      } else {
        console.log('  ok    AOI del visor derivado del manifest (' + m2.join(', ') + ')');
      }
    } else {
      bad += 1; console.log('  FALLO setAoi no existe: el AOI del visor volvio a estar a fuego');
    }
  } catch (e) { bad += 1; console.log('  FALLO AOI -> ' + e.message); }

  /* El bbox del catalogo de pasadas se permutaba a lat,lon y pedia escenas
   * del mar de Arabia. El orden correcto es el del manifest tal cual. */
  try {
    if (typeof ctx.bboxLooksSane === 'function' && manifest.aoi) {
      const tracks2 = rd('tracks.geojson');
      if (tracks2) { ctx.buildHistory(tracks2); }
      const swapped = [manifest.aoi[1], manifest.aoi[0], manifest.aoi[3], manifest.aoi[2]];
      if (!ctx.bboxLooksSane(manifest.aoi)) {
        bad += 1; console.log('  FALLO manifest.aoi no contiene los buques del build');
      } else if (ctx.bboxLooksSane(swapped)) {
        bad += 1; console.log('  FALLO el guardia de bbox no detecta la permutacion');
      } else { console.log('  ok    bbox del catalogo de pasadas (guardia detecta ' +
        'la permutacion contra ' + ctx.knownPositions().length + ' posiciones)'); }
    }
  } catch (e) { bad += 1; console.log('  FALLO bbox -> ' + e.message); }

  /* El filtro de buques manda sobre el MAPA, no solo sobre la lista. Se
   * comprueba el predicado compartido: si lista y mapa divergieran, el mapa
   * estaria ocultando cosas que la lista dice tener. */
  try {
    if (typeof ctx.vesselVisible === 'function') {
      const all = Object.keys(ctx.HIST);
      const n0 = all.filter(ctx.vesselVisible).length;
      const hasSan = Object.values(ctx.VINFO || {}).some(r => r.sanctions && r.sanctions.length);
      if (hasSan) { ctx.VFILTER.sanctioned = true; }
      else { ctx.VFILTER.flag.Finland = false; }
      const n1 = all.filter(ctx.vesselVisible).length;
      const onMap = all.filter(ctx.visibleOnMap).length;
      ctx.VFILTER.onMap = false;
      const offMap = all.filter(ctx.visibleOnMap).length;
      ctx.VFILTER.onMap = true;
      ctx.VFILTER.sanctioned = false;
      ctx.VFILTER.flag = {};
      if (!(n1 > 0 && n1 < n0)) {
        bad += 1; console.log('  FALLO vesselVisible: ' + n0 + ' -> ' + n1);
      } else if (onMap !== n1) {
        bad += 1; console.log('  FALLO lista y mapa discrepan: ' + n1 + ' vs ' + onMap);
      } else if (offMap !== n0) {
        bad += 1; console.log('  FALLO el interruptor onMap no libera el mapa: ' + offMap);
      } else {
        console.log('  ok    filtro al mapa (' + n0 + ' -> ' + n1 +
          ', lista y mapa de acuerdo, interruptor libera)');
      }
    }
  } catch (e) { bad += 1; console.log('  FALLO filtro al mapa -> ' + e.message); }

  /* La barra de progreso de imagen se quedaba clavada porque se contaba
   * `tileloadstart` contra solo dos finales. Leaflet tiene TRES: load, error
   * y abort. Este test fija el invariante en vez del sintoma. */
  try {
    const img = fs.readFileSync('imagery.js', 'utf8');
    const miss = ['tileloadstart', 'tileload', 'tileerror', 'tileabort']
      .filter(ev => !img.includes("'" + ev + "'"));
    if (miss.length) {
      bad += 1; console.log('  FALLO eventos de tesela sin manejar: ' + miss.join(', '));
    } else { console.log('  ok    ciclo de vida de tesela completo (load/error/abort)'); }
  } catch (e) { bad += 1; console.log('  FALLO lectura imagery.js -> ' + e.message); }

  /* La instantanea temporal. Se comprueba porque fallaba en silencio:
   * buildHistory escribia `t` y snapshotAt leia `at`, asi que devolvia cero
   * buques sin lanzar nada y mover el cursor no pintaba nada. */
  try {
    const tracks = rd('tracks.geojson');
    if (tracks && typeof ctx.buildHistory === 'function') {
      ctx.buildHistory(tracks);
      const ks = Object.keys(ctx.HIST);
      const pts = ctx.HIST[ks[0]].pts;
      const n = ctx.snapshotAt(pts[Math.floor(pts.length / 2)].t).length;
      if (!(ks.length > 0 && n > ks.length * 0.5)) {
        bad += 1; console.log('  FALLO snapshotAt: ' + n + ' de ' + ks.length + ' buques');
      } else { console.log('  ok    snapshotAt (' + n + '/' + ks.length + ')'); }
    }
  } catch (e) { bad += 1; console.log('  FALLO snapshotAt -> ' + e.message); }

  /* El resumen de la alerta. Se recorren los SIETE indicadores con alertas
   * reales: si un detector cambia el nombre de un campo de `evidence`, el
   * bloque se queda mudo o imprime «null» y aqui se ve. */
  try {
    const fc = rd('alerts.geojson');
    const seen = {}, empty = [], dirty = [];
    fc.features.forEach(f => {
      const ind = f.properties.indicator;
      if (seen[ind]) { return; }
      seen[ind] = true;
      const g = ctx.alertGist(f.properties);
      if (!g || !g.rows.length) { empty.push(ind); return; }
      const bad = g.rows.filter(r => /null|undefined|NaN/.test(String(r[1])));
      if (bad.length) { dirty.push(ind + ':' + bad.map(r => r[0]).join()); }
    });
    const n = Object.keys(seen).length;
    if (empty.length || dirty.length || n < 7) {
      bad += 1;
      console.log('  FALLO resumen de alerta: ' + n + '/7 indicadores'
                  + (empty.length ? ', vacios ' + empty.join() : '')
                  + (dirty.length ? ', sucios ' + dirty.join(' ') : ''));
    } else {
      const rows = Object.keys(seen).map(i =>
        ctx.alertGist(fc.features.find(f => f.properties.indicator === i).properties).rows.length);
      console.log('  ok    resumen de alerta (7 indicadores, '
                  + Math.min(...rows) + '-' + Math.max(...rows) + ' filas, sin huecos)');
    }
  } catch (e) { bad += 1; console.log('  FALLO resumen de alerta -> ' + e.message); }

  /* Que mover el cursor CAMBIE lo que se dibuja. Es la prueba que habria
   * cazado el fallo que reporto el usuario: el reloj avanzaba y los barcos
   * seguian clavados, porque la vista activa no dependia del cursor. Comparar
   * conjuntos de MMSI no basta -- casi siempre son los mismos buques -- asi
   * que se comparan las POSICIONES. */
  try {
    /* Se muestrea DENTRO de la grabacion, no a porcentajes del intervalo.
     * El almacen tiene 8 ventanas de cobertura en 15,5 dias: entre ellas
     * snapshotAt devuelve la ultima posicion conocida, asi que dos instantes
     * del mismo hueco dan la MISMA escena, y con razon. Se toman marcas de
     * tiempo reales de la traza mas densa, que por definicion caen dentro de
     * una ventana. */
    const busiest = Object.keys(ctx.HIST)
      .reduce((a, k) => ctx.HIST[k].pts.length > ctx.HIST[a].pts.length ? k : a,
              Object.keys(ctx.HIST)[0]);
    const pts = ctx.HIST[busiest].pts;
    const at = t => ctx.snapshotAt(t)
      .map(r => r.mmsi + '@' + r.fix.lat.toFixed(4) + ',' + r.fix.lon.toFixed(4))
      .sort().join('|');
    const ts = [0.5, 0.75, 0.95].map(f => pts[Math.floor(pts.length * f)].t);
    const scenes = ts.map(at);
    const uniq = new Set(scenes).size;
    if (!scenes[0].length || uniq < 3) {
      bad += 1;
      console.log('  FALLO el cursor no mueve los buques: ' + uniq
                  + ' escenas distintas de 3 instantes grabados');
    } else {
      console.log('  ok    el cursor mueve los buques (3 instantes grabados, '
                  + '3 escenas distintas, ~'
                  + scenes[0].split('|').length + ' buques)');
    }
  } catch (e) { bad += 1; console.log('  FALLO cursor vs buques -> ' + e.message); }

  /* Las capas de Copernicus Marine. Lo fragil es la ETIQUETA DEL DATASET:
   * el identificador lleva un sufijo de version que Copernicus rota en cada
   * Service Release, y una URL con la etiqueta vieja deja de servir teselas
   * sin avisar. Se exige que el catalogo la lleve y que el modulo elija la
   * mas alta en vez de fijarla. */
  try {
    const cat = rd('marine_layers.json');
    const problemas = [];
    if (!cat || !cat.layers || cat.layers.length < 15) {
      problemas.push('catalogo vacio o incompleto');
    } else {
      const sinTag = cat.layers.filter(l => !l.dataset_tag);
      if (sinTag.length) { problemas.push(sinTag.length + ' capas sin etiqueta de dataset'); }
      const grupos = new Set(cat.layers.map(l => l.group));
      if (grupos.size < 4) { problemas.push('solo ' + grupos.size + ' grupos'); }
      /* La corriente es la razon de ser de todo esto. */
      if (!cat.layers.some(l => l.variable === 'sea_water_velocity')) {
        problemas.push('falta la corriente, que es lo unico que FMI no da');
      }
      /* Y el error de 87 grados tiene que viajar con el catalogo. */
      if (!cat.caveat || !/\d+ deg/.test(cat.caveat)) {
        problemas.push('el catalogo no lleva el error de direccion de corriente');
      }
    }
    /* Que elija la etiqueta MAS ALTA. Se comprueba el comportamiento, no una
     * linea: la primera version de esta prueba afirmaba el texto exacto de
     * una comparacion y fallo en cuanto se refactorizo, sin que nada
     * estuviera roto. Un test que se rompe al mover codigo correcto enseña
     * a ignorar los tests. */
    const probe = require('child_process').execSync(
      'python3 -c "' +
      'from custody import marine;' +
      'x=marine._newest(\'<Layer><ows:Identifier>P/ds_202301/v</ows:Identifier>' +
      '<ows:Title>t</ows:Title></Layer>' +
      '<Layer><ows:Identifier>P/ds_202611/v</ows:Identifier>' +
      '<ows:Title>t</ows:Title></Layer>\');' +
      'print(x[\'v\'][\'dataset_tag\'])"',
      { cwd: path.join(__dirname, '..'), encoding: 'utf8' }).trim();
    if (probe !== '202611') {
      problemas.push('elige la etiqueta ' + probe + ' en vez de la mas alta (202611)');
    }
    if (problemas.length) {
      bad += 1;
      console.log('  FALLO Copernicus Marine: ' + problemas.join(' · '));
    } else {
      console.log('  ok    Copernicus Marine (' + cat.layers.length + ' capas en '
                  + new Set(cat.layers.map(l => l.group)).size
                  + ' grupos, etiqueta de dataset elegida por version)');
    }
  } catch (e) { bad += 1; console.log('  FALLO Copernicus Marine -> ' + e.message); }

  /* Las escalas de color. Veinte capas de colores sin escala no aportan
   * nada, que es literalmente lo que reporto el usuario. Se exige que TODAS
   * la lleven y que la URL este bien formada: el servicio declara el FORMAT
   * doblemente escapado y asi da 400, y solo acepta SVG. */
  try {
    const cat = rd('marine_layers.json');
    const sin = cat.layers.filter(l => !l.legend);
    const malEscapadas = cat.layers.filter(l => l.legend && /%25/.test(l.legend));
    const sinSvg = cat.layers.filter(l => l.legend && !/svg/i.test(l.legend));
    /* Y que el estilo de la TESELA sea el mismo que el de la leyenda, o la
     * escala describe una paleta que no se esta pintando. */
    const desparejas = cat.layers.filter(l =>
      l.legend && l.style &&
      !decodeURIComponent(l.legend).includes(l.style));
    if (sin.length || malEscapadas.length || sinSvg.length || desparejas.length) {
      bad += 1;
      console.log('  FALLO escalas de color: ' + sin.length + ' sin escala, '
                  + malEscapadas.length + ' mal escapadas, ' + sinSvg.length
                  + ' sin svg, ' + desparejas.length + ' con paleta distinta a la tesela');
    } else {
      console.log('  ok    escalas de color (' + cat.layers.length
                  + '/' + cat.layers.length + ', misma paleta que la tesela)');
    }
  } catch (e) { bad += 1; console.log('  FALLO escalas de color -> ' + e.message); }

  /* AISHub: la capa existe para enseñar la cobertura que NO tenemos, asi que
   * lo que hay que comprobar es que marque las del hueco. */
  try {
    const fc = rd('aishub_stations.geojson');
    const gap = fc.features.filter(f => f.properties.in_gap);
    const gotland = fc.features.filter(f =>
      /visby|faro|fårö/i.test(f.properties.location || ''));
    if (!gap.length || !gotland.length) {
      bad += 1;
      console.log('  FALLO AISHub: ' + gap.length + ' en el hueco, '
                  + gotland.length + ' en Gotland');
    } else {
      console.log('  ok    AISHub (' + fc.features.length + ' estaciones, '
                  + gap.length + ' en el hueco de cobertura, Gotland incluida)');
    }
  } catch (e) { bad += 1; console.log('  FALLO AISHub -> ' + e.message); }

  /* Las alertas en tiempo de ejecucion. Lo que hay que proteger es que NO
   * se reimplementen los indicadores en JavaScript: dos copias de una regla
   * de deteccion es como se consigue que la demo y el informe no coincidan.
   * El visor recibe, une y avisa; el calculo vive en custody/indicators.py y
   * lo ejecutan tanto el build como el servidor. */
  try {
    const js = String(fs.readFileSync('livealerts.js'));
    const problemas = [];
    /* Si alguien empieza a calcular aqui, estas firmas apareceran. */
    [['umbral de velocidad', /slow_window|drag_band|1\.0\s*&&|sog\s*[<>]=?\s*5/],
     ['distancia a corredor', /min_distance_m\s*=/],
     ['ventana de merodeo', /loiter|dwell_s/]].forEach(function (p) {
      if (p[1].test(js)) { problemas.push('el visor calcula ' + p[0]); }
    });
    if (!/EventSource/.test(js)) {
      problemas.push('no usa EventSource: volveria a sondear y a añadir retardo');
    }
    if (!/buildOnly/.test(js) || !/winStart/.test(js)) {
      problemas.push('no separa build de vivo por ventana: duplicaria alertas');
    }
    /* Y que el motor exista en Python, usando el mismo modulo que el build. */
    const py = String(fs.readFileSync('../custody/live.py'));
    if (!/from custody import[^\n]*indicators/.test(py) || !/indicators\.run\(/.test(py)) {
      problemas.push('custody/live.py no usa indicators.run()');
    }
    if (problemas.length) {
      bad += 1;
      console.log('  FALLO alertas en vivo: ' + problemas.join(' · '));
    } else {
      console.log('  ok    alertas en vivo (un solo motor en Python, push por SSE, '
                  + 'union por ventana sin duplicar)');
    }
  } catch (e) { bad += 1; console.log('  FALLO alertas en vivo -> ' + e.message); }

  /* La cobertura viva. Lo que hay que proteger es que la pista NO dependa
   * del manifest: venia de ahi y por eso se congelaba en el instante del
   * build, lo que a las 42 h se leia como «se han perdido datos». */
  try {
    const src = String(fs.readFileSync('time.js'));
    const problemas = [];
    if (!/fetch\('\/coverage'\)/.test(src)) {
      problemas.push('initTime ya no pide /coverage al servidor');
    }
    /* El borde de lo EVALUADO, que ya no es el del build: lo marca el motor.
     * Lo que queda mas alla se dibuja hueco, y ahora eso solo pasa cuando de
     * verdad falta --- sin motor, o con un hueco mayor que su ventana. */
    const lan = String(fs.readFileSync('lanes.js'));
    if (!/TIME\.builtTo/.test(lan) || !/class="raw"/.test(lan)
        || !/function liveEdge/.test(lan)) {
      problemas.push('no se distinguen las ventanas sin evaluar');
    }
    if (/function laneHtml/.test(src)) {
      problemas.push('dos constructores de pista: laneHtml sigue en time.js');
    }
    /* Y que el endpoint exista en el servidor, con su propio lector. */
    const srv = String(fs.readFileSync('server.py'));
    if (!/\/coverage/.test(srv) || !/coverage_windows/.test(srv)) {
      problemas.push('el servidor no expone /coverage');
    }
    if (problemas.length) {
      bad += 1;
      console.log('  FALLO cobertura viva: ' + problemas.join(' · '));
    } else {
      console.log('  ok    cobertura viva (la pista se recalcula del polllog, '
                  + 'no del manifest, y marca lo no compilado)');
    }
  } catch (e) { bad += 1; console.log('  FALLO cobertura viva -> ' + e.message); }

  /* LAS TRAZAS EN VIVO FUSIONADAS EN HIST.
   *
   * Esto es lo que quita de en medio el «hay que compilar otra vez», asi que
   * se comprueba el efecto, no la intencion: tras fusionar una traza
   * posterior al build, snapshotAt() en ese instante tiene que devolver ese
   * buque. Antes el visor no tenia mas fuente que el build y la respuesta
   * era vacio. */
  try {
    const built = ((ctx.manifest.time || {}).dataset_end_ms) || 0;
    const after = built + 3 * 3600e3;            /* tres horas DESPUES */
    const antes = ctx.snapshotAt(after).length;
    const mmsi = 999000111;
    ctx.mergeLiveTracks({
      type: 'FeatureCollection',
      features: [{
        type: 'Feature', id: mmsi,
        geometry: { type: 'MultiLineString', coordinates: [[[20.0, 59.0], [20.1, 59.0]]] },
        properties: { mmsi: mmsi, name: 'PRUEBA VIVA', ship_type: 70,
                      times: [[after - 60000, after - 30000]],
                      sogs: [[12.0, 12.1]], hdgs: [[90, 90]] }
      }],
      properties: { mode: 'live' }
    });
    const rows = ctx.snapshotAt(after);
    const mio = rows.filter(r => String(r.mmsi) === String(mmsi));
    const errs = [];
    if (!mio.length) { errs.push('el buque vivo no aparece en la instantanea'); }
    if (mio.length && mio[0].age > 60000) { errs.push('edad mal calculada'); }
    if (ctx.LIVEV.added !== 2) { errs.push('fixes fusionados: ' + ctx.LIVEV.added); }
    /* Y que REFUNDIR lo mismo no duplique: build y motor se solapan a
     * proposito, asi que la deduplicacion por marca de tiempo es lo que
     * evita que cada ciclo engorde el historial. */
    const n1 = ctx.HIST[String(mmsi)].pts.length;
    ctx.mergeLiveTracks({
      type: 'FeatureCollection',
      features: [{
        type: 'Feature', id: mmsi,
        geometry: { type: 'MultiLineString', coordinates: [[[20.0, 59.0], [20.1, 59.0]]] },
        properties: { mmsi: mmsi, name: 'PRUEBA VIVA',
                      times: [[after - 60000, after - 30000]],
                      sogs: [[12.0, 12.1]], hdgs: [[90, 90]] }
      }],
      properties: {}
    });
    if (ctx.HIST[String(mmsi)].pts.length !== n1) {
      errs.push('refundir duplica: ' + n1 + ' -> ' + ctx.HIST[String(mmsi)].pts.length);
    }
    delete ctx.HIST[String(mmsi)];
    /* Y que el servidor lo sirva con el MISMO constructor que el build. */
    const srv = String(fs.readFileSync('server.py'));
    if (!/\/vessels\/live/.test(srv)) { errs.push('el servidor no expone /vessels/live'); }
    const py = String(fs.readFileSync(path.join('..', 'custody', 'live.py')));
    if (!/ais\.tracks_geojson/.test(py)) {
      errs.push('el motor no usa el constructor compartido');
    }
    const bl = String(fs.readFileSync(path.join('..', 'build.py')));
    if (!/ais\.tracks_geojson/.test(bl)) {
      errs.push('el build no usa el constructor compartido');
    }
    if (errs.length) { bad += 1; console.log('  FALLO trazas en vivo: ' + errs.join(' · ')); }
    else {
      console.log('  ok    trazas en vivo fusionadas (instantanea ' + antes + ' -> '
                  + rows.length + ' tres horas despues del build, sin duplicar al refundir)');
    }
  } catch (e) { bad += 1; console.log('  FALLO trazas en vivo -> ' + e.message); }

  /* UNA PISTA POR FUENTE, AGRUPADAS Y PLEGABLES.
   *
   * Lo que hay que proteger es que las ventanas se LEAN de cada servicio y no
   * se escriban a mano: una cadencia a mano se queda vieja sin avisar, y asi
   * estabamos pidiendo medias diarias de corriente creyendo que eran
   * horarias. Y que laneHasAt() distinga de verdad, porque de el depende la
   * respuesta a «puedo superponer estas dos capas». */
  try {
    const errs = [];
    /* El catalogo, cargado como lo carga el visor. Sin esto `MARINE.cat`
     * queda vacio y la comprobacion de las pistas CMEMS pasaba EN VACIO:
     * decia «0 de CMEMS» y seguia. Una prueba que no puede fallar no es una
     * prueba. */
    ctx.loadMarine(rd('marine_layers.json'));
    ctx.loadEmodnet(rd('emodnet_layers.json'));
    ctx.LANES.srv = { generated_ms: Date.now(), sources: [
      { id: 'aishub', group: 'ours', name: 'AIS · AISHub', kind: 'windows',
        windows_ms: [], state: 'needs_key' },
      { id: 'fmi_wind', group: 'forcing', name: 'FMI HARMONIE · wind', kind: 'span',
        start_ms: Date.now(), end_ms: Date.now() + 49 * 3600e3, step_s: 3600,
        forecast: true }
    ] };
    const g = ctx.laneModel();
    if (!g.ours.length || !g.forcing.length || !g.static.length) {
      errs.push('faltan grupos: ' + Object.keys(g).map(k => k + '=' + g[k].length).join(' '));
    }
    /* Las capas CMEMS se agrupan por CONJUNTO DE DATOS, no una pista por
     * capa: veinte pistas serian ruido y ademas redundantes, porque las que
     * comparten dataset comparten eje temporal por definicion. */
    const cm = g.forcing.filter(l => l.cls === 'cmems');
    const nLayers = (((ctx.MARINE || {}).cat || {}).layers || []).length;
    if (!nLayers) { errs.push('el catalogo CMEMS no se cargo: nada que comprobar'); }
    if (!cm.length) { errs.push('las capas CMEMS no producen pista'); }
    if (cm.length >= nLayers && nLayers) {
      errs.push('una pista por capa (' + cm.length + ') en vez de por dataset');
    }
    if (cm.length && !cm.every(l => l.step_s > 0 && l.start && l.end)) {
      errs.push('alguna pista CMEMS sin ventana ni cadencia declarada');
    }
    /* Ningun nombre de pista puede llevar una clave interna: «CMEMS
     * currents_global» salio asi en pantalla una vez. */
    const fugas = [].concat(g.forcing, g.baseline, g.ours)
      .map(l => l.name).filter(n => /_/.test(n));
    if (fugas.length) { errs.push('clave interna en el nombre: ' + fugas.join(', ')); }

    /* laneHasAt: dentro si, fuera no. Sin esto el recuento de solape diria
     * que todo coincide con todo. */
    const fmi = g.forcing.filter(l => l.id === 'fmi_wind')[0];
    if (!fmi || !ctx.laneHasAt(fmi, Date.now() + 3600e3)
        || ctx.laneHasAt(fmi, Date.now() - 48 * 3600e3)) {
      errs.push('laneHasAt no acota el intervalo de un modelo');
    }
    const est = g.static[0];
    if (!ctx.laneHasAt(est, 0) || !ctx.laneHasAt(est, Date.now())) {
      errs.push('la cartografia deberia valer en cualquier instante');
    }
    /* La linea base de EMODnet: una pista por PRODUCTO, y lo que hay que ver
     * es el DESFASE. La de Cogea termina en 2024 y la de EMSA llega al mes
     * pasado; si las dos salieran iguales, alguien las habria mezclado. */
    if (process.env.SMOKE_DEBUG) {
      console.log('    [dbg] EMOD.cat layers =', (((ctx.EMOD||{}).cat||{}).layers||[]).length,
                  ' grupos =', JSON.stringify(Object.keys(g).map(k => k + ':' + g[k].length)));
    }
    const eb = (g.baseline || []).filter(l => l.cls === 'emod');
    const nEm = (((ctx.EMOD || {}).cat || {}).layers || []).length;
    if (!nEm) { errs.push('el catalogo EMODnet no se cargo: nada que comprobar'); }
    if (eb.length !== 2) {
      errs.push('se esperaban 2 pistas EMODnet (EMSA y Cogea), hay ' + eb.length);
    }
    if (eb.length === 2) {
      const ends = eb.map(l => l.end).sort((a, b) => a - b);
      if (!(ends[1] - ends[0] > 300 * 86400e3)) {
        errs.push('las dos lineas base acaban casi a la vez: '
                  + eb.map(l => new Date(l.end).toISOString().slice(0, 7)).join(' / '));
      }
    }
    /* Y que el instante se elija de la LISTA declarada, no redondeando: fuera
     * de ella el servicio devuelve una tesela vacia, que sobre el mapa se lee
     * como «aqui no pasa nadie». */
    const rd_all = ctx.emodById('emod_routedensity_all');
    if (!rd_all) { errs.push('falta la capa de densidad de rutas'); }
    else {
      const pick = ctx.emodPick(rd_all, Date.now());
      if (!pick || rd_all.time.values.indexOf(pick.time) < 0) {
        errs.push('emodPick devuelve un instante que el servicio no declara');
      }
      const far = ctx.emodPick(rd_all, Date.parse('2010-01-01T00:00:00Z'));
      if (!far || far.off_ms < 300 * 86400e3) {
        errs.push('emodPick no mide la distancia al cursor');
      }
    }

    /* El recuento de solape, que es LA respuesta a la pregunta. */
    const r = ctx.lanesAt(Date.now());
    if (!(r.total > 1)) { errs.push('lanesAt no cuenta fuentes'); }
    /* Plegable y con el estado recordado: el panel se repinta constantemente
     * y sin persistirlo cada repintado reabriria lo que acabas de cerrar,
     * que es el fallo que ya tuvo el panel del mapa. */
    const h = ctx.lanesHtml();
    if (!/details class="lane-g/.test(h)) { errs.push('las pistas no son plegables'); }
    ctx.lanesSetOpen('forcing', false);
    if (/data-lg="forcing" open/.test(ctx.lanesHtml())
        || ctx.lanesOpen('forcing') !== false) {
      errs.push('el plegado no se recuerda entre repintados');
    }
    ctx.lanesSetOpen('forcing', true);
    /* Y que el servidor sirva el eje temporal de cada fuente. */
    const srv = String(fs.readFileSync('server.py'));
    if (!/\/sources\/time/.test(srv)) { errs.push('el servidor no expone /sources/time'); }
    if (errs.length) { bad += 1; console.log('  FALLO pistas por fuente: ' + errs.join(' · ')); }
    else {
      const n = Object.keys(g).reduce((a, k) => a + g[k].length, 0);
      /* El numero de grupos se CUENTA. Estaba escrito a mano como «4» y al
       * añadir la linea base siguio diciendo 4: un mensaje de prueba que
       * miente es peor que no tenerlo. */
      const ng = (h.match(/details class="lane-g/g) || []).length;
      console.log('  ok    una pista por fuente (' + n + ' pistas en ' + ng
                  + ' grupos plegables, ' + cm.length + ' de CMEMS y ' + eb.length
                  + ' de EMODnet por dataset, ' + r.hit.length + '/' + r.total
                  + ' con dato en el cursor)');
    }
  } catch (e) { bad += 1; console.log('  FALLO pistas por fuente -> ' + e.message); }

  /* Que un build viejo se AVISE. La pista de cobertura se corta por la
   * derecha cuando el build se queda atras, y eso se lee como «se perdieron
   * datos»: paso con 42 h de desfase y 115.617 registros grabados que el
   * visor no habia visto. El dato estaba intacto; lo que faltaba era decirlo. */
  try {
    const end = ((ctx.manifest.time || {}).dataset_end_ms) || 0;
    const h = (Date.now() - end) / 3600e3;
    const dicho = ctx.buildAgeH();
    const src = String(fs.readFileSync('time.js'));
    if (Math.abs(dicho - h) > 0.1) {
      bad += 1;
      console.log('  FALLO buildAgeH() da ' + dicho.toFixed(1) + ' h y deberia dar '
                  + h.toFixed(1));
    } else if (!/stale-note/.test(src) || !/live-note/.test(src)
               || !ctx.t('lane_live_cover') || !ctx.t('lane_nolive')) {
      bad += 1;
      console.log('  FALLO no se dice el estado del tramo posterior al build');
    } else {
      /* Y que el aviso diga la verdad: con motor cubriendo el tramo hay que
       * decir que esta cubierto, no «vuelve a compilar». Las dos frases
       * viejas se borraron del catalogo para que nadie las reviva. */
      const revividas = ['lane_raw', 'lane_stale'].filter(k => ctx.t(k) !== k);
      if (revividas.length) {
        bad += 1;
        console.log('  FALLO han vuelto frases de «compila otra vez»: ' + revividas);
      } else {
        console.log('  ok    estado del tramo posterior al build ('
                    + h.toFixed(0) + ' h de desfase, umbral ' + ctx.BUILD_STALE_H
                    + ' h, ' + (h > ctx.BUILD_STALE_H ? 'se explica quien lo cubre'
                                                      : 'build fresco') + ')');
      }
    }
  } catch (e) { bad += 1; console.log('  FALLO aviso de build viejo -> ' + e.message); }

  /* Un solo reloj. Habia dos: la linea temporal gobernaba el mapa y el panel
   * del buque animaba su propio cometa sin tocar TIME.cursor, asi que
   * reproducir las ultimas 24 h de un barco dejaba el resto del mapa
   * congelado en otro instante. Se comprueban las tres ataduras. */
  try {
    const m = Object.keys(ctx.HIST)
      .reduce((a, k) => ctx.HIST[k].pts.length > ctx.HIST[a].pts.length ? k : a,
              Object.keys(ctx.HIST)[0]);
    const problemas = [];

    /* 1. Elegir rango en el buque encuadra la linea temporal en ese rango. */
    ctx.showVessel(m, 24 * 3600e3, null);
    const span = (ctx.TIME.v1 - ctx.TIME.v0) / 3600e3;
    if (Math.abs(span - 24) > 0.5) {
      problemas.push('el rango de 24 h del buque deja la barra en ' + span.toFixed(1) + ' h');
    }

    /* 2. animateTrack conduce el cursor: se busca la llamada, porque sin
     *    requestAnimationFrame no se puede ejecutar aqui. */
    const src = String(fs.readFileSync('vessel.js'));
    if (!/ANIM\.drive[\s\S]{0,160}setCursor\(/.test(src)) {
      problemas.push('animateTrack ya no empuja el cursor global');
    }

    /* 3. Las dos reproducciones se excluyen: arrancar una para la otra. */
    if (!/function togglePlay\(\)[\s\S]{0,240}stopAnim\(\)/.test(String(fs.readFileSync('time.js')))) {
      problemas.push('el Play global no para la animacion del buque');
    }
    if (!/function animateTrack[\s\S]{0,900}stopPlay\(\)/.test(src)) {
      problemas.push('la animacion del buque no para el Play global');
    }

    /* 4. Y que no hayan vuelto dos botones para volver al presente. */
    if (/tb-resync/.test(String(fs.readFileSync('time.js')))) {
      problemas.push('ha vuelto «Back to now», que duplica a «Latest»');
    }

    ctx.closeHistory();
    if (problemas.length) {
      bad += 1;
      console.log('  FALLO un solo reloj: ' + problemas.join(' · '));
    } else {
      console.log('  ok    un solo reloj (rango del buque encuadra la barra, '
                  + 'la animacion conduce el cursor, las dos reproducciones se '
                  + 'excluyen, un solo «Latest»)');
    }
  } catch (e) { bad += 1; console.log('  FALLO un solo reloj -> ' + e.message); }

  /* La costa de HELCOM bajo demanda. Lo que hay que proteger no es que
   * dibuje -- eso se ve -- sino que dos vistas parecidas pidan la MISMA URL:
   * las celdas se alinean a una rejilla de 0,5 grados, no al encuadre. Si
   * alguien cambia eso por el bbox exacto, cada arrastre del raton seria una
   * descarga nueva y la cache de disco dejaria de servir para nada. */
  try {
    const mk = (w, s, e, n, z) => ctx.coastCells(
      { getWest: () => w, getSouth: () => s, getEast: () => e, getNorth: () => n }, z);
    const a = mk(24.90, 60.10, 25.10, 60.30, 11);
    const b = mk(24.93, 60.12, 25.07, 60.28, 11);   /* casi la misma vista */
    const mismas = JSON.stringify(a) === JSON.stringify(b);
    /* Y que el zoom baje el detalle pedido, o se bajan 8 m para pintar 150. */
    const fino = ctx.coastOffset(13), grueso = ctx.coastOffset(8);
    /* Y que se pida del CENTRO hacia fuera. Cortar la lista en orden de
     * generacion --suroeste primero-- hacia que a zoom bajo se pidieran doce
     * cuadros de oceano vacio y la capa saliera encendida y vacia. Fallo
     * silencioso: ni error, ni aviso, ni una linea. */
    const src = String(fs.readFileSync('coasthd.js'));
    if (!/getCenter\(\)[\s\S]{0,400}cells\.sort/.test(src)) {
      throw new Error('coastRefresh ya no ordena las celdas por cercania al centro');
    }
    /* El corte de islotes tiene que aflojar al acercarse, o a zoom 12 se
     * pierde el archipielago; y apretar al alejarse, o son 90.000 objetos. */
    if (!(ctx.coastMinKm(12) < ctx.coastMinKm(8) &&
          ctx.coastMinKm(8) < ctx.coastMinKm(5))) {
      throw new Error('el corte de islotes no escala con el zoom');
    }
    if (!mismas || !(fino < grueso) || !a.length) {
      bad += 1;
      console.log('  FALLO costa bajo demanda: celdas ' + (mismas ? 'estables' : 'DISTINTAS')
                  + ' para la misma vista, offset z13=' + fino + ' z8=' + grueso);
    } else {
      console.log('  ok    costa HELCOM bajo demanda (' + a.length
                  + ' celdas alineadas, del centro hacia fuera, generalizacion '
                  + fino + '-' + grueso + ' deg, islotes ' + ctx.coastMinKm(12)
                  + '-' + ctx.coastMinKm(5) + ' km segun zoom)');
    }
  } catch (e) { bad += 1; console.log('  FALLO costa bajo demanda -> ' + e.message); }

  /* Las cuencas. Ya no son rectangulos nuestros sino las 17 subcuencas
   * HELCOM nivel 2, asi que lo que hay que comprobar cambia: que esten las
   * 17, que se agrupen en las 7 de HELCOM, y sobre todo que NINGUN buque se
   * quede sin clasificar -- para eso existe el grupo de aguas interiores.
   * Antes, enfocar hacia desaparecer del mapa a los del lago Ladoga. */
  try {
    const fc = rd('basins.geojson');
    const n = fc.features.length;
    const majors = [...new Set(fc.features.map(f => f.properties.major))];
    const sinClasificar = rd('positions.geojson').features
      .filter(f => ctx.basinOf(f.geometry.coordinates[0], f.geometry.coordinates[1]) === null);
    const inland = rd('positions.geojson').features
      .filter(f => ctx.basinOf(f.geometry.coordinates[0], f.geometry.coordinates[1]) === 'inland');
    if (n !== 17 || majors.length !== 7 || sinClasificar.length) {
      bad += 1;
      console.log('  FALLO subcuencas HELCOM: ' + n + ' unidades, ' + majors.length
                  + ' grupos, ' + sinClasificar.length + ' buques sin clasificar');
    } else {
      console.log('  ok    subcuencas HELCOM (17 nivel 2 en 7 grupos, 0 buques sin '
                  + 'clasificar, ' + inland.length + ' en aguas interiores)');
    }
  } catch (e) { bad += 1; console.log('  FALLO subcuencas HELCOM -> ' + e.message); }

  /* Y que enfocar FILTRE. Era un zoom con una mascara encima: la lista
   * seguia contando las alertas del Baltico entero.
   *
   * Se apaga la ventana temporal primero. La primera version de esta prueba
   * no lo hacia y media una diferencia que no era del foco: entre las dos
   * llamadas, otra comprobacion habia movido el cursor y era ESO lo que
   * cambiaba la cuenta. Daba verde por el motivo equivocado. */
  try {
    const tf = ctx.TIME_FILTER.on;
    ctx.TIME_FILTER.on = false;
    const sinFoco = () => { ctx.BASIN = { id: null }; return ctx.visibleAlertFeatures().length; };
    const conFoco = () => { ctx.BASIN = { id: 'GUF' }; return ctx.visibleAlertFeatures().length; };
    const n0 = sinFoco(), n1 = conFoco();
    const nota = ctx.basinFilterNote('alerts');
    const n2 = sinFoco();
    ctx.TIME_FILTER.on = tf;
    /* El numero del aviso tiene que ser exactamente lo que el foco esconde,
     * no el total: antes contaba sobre las 1.090 y exageraba. */
    const dice = +(/(\d+)/.exec(nota) || [0, 0])[1];
    if (!(n1 < n0 && n2 === n0 && dice === n0 - n1)) {
      bad += 1;
      console.log('  FALLO foco por cuenca: ' + n0 + ' -> ' + n1 + ' -> ' + n2
                  + ', el aviso dice ' + dice + ' y deberia decir ' + (n0 - n1));
    } else {
      console.log('  ok    el foco por cuenca filtra y cuenta bien (' + n0 + ' -> '
                  + n1 + ', avisa de ' + dice + ' ocultas, vuelve a ' + n2 + ')');
    }
  } catch (e) { bad += 1; console.log('  FALLO foco por cuenca -> ' + e.message); }

  /* Que no haya vuelto a aparecer una segunda capa de buques. Hubo tres
   * dibujando lo mismo desde la misma base de datos. */
  try {
    const extra = ['live', 'positions'].filter(k => ctx.layers[k]);
    if (extra.length) {
      bad += 1;
      console.log('  FALLO hay otra capa de buques ademas de la instantanea: '
                  + extra.join(', '));
    } else {
      console.log('  ok    una sola capa de buques (la instantanea del cursor)');
    }
  } catch (e) { bad += 1; console.log('  FALLO capas de buque -> ' + e.message); }

  /* Los buques oidos UNA vez. No tienen traza, asi que vivian solo en la capa
   * que se quito; si no se siembran en HIST desaparecen del mapa sin avisar. */
  try {
    const pos = rd('positions.geojson');
    const sin = pos.features
      .map(f => String(f.properties.mmsi))
      .filter(m => !ctx.HIST[m]);
    const singles = Object.keys(ctx.HIST).filter(m => ctx.HIST[m].single).length;
    if (sin.length) {
      bad += 1;
      console.log('  FALLO ' + sin.length + ' buques de positions no estan en el '
                  + 'historial: se perderian del mapa');
    } else {
      console.log('  ok    buques de un solo avistamiento en el historial ('
                  + singles + ' sembrados, 0 perdidos)');
    }
  } catch (e) { bad += 1; console.log('  FALLO buques de un solo fix -> ' + e.message); }

  /* EL CATALOGO DE CAPAS: una entrada por capa, clasificada en los dos ejes,
   * y nada suelto.
   *
   * Antes esto comprobaba LAYER_GROUPS, que solo conocia las del build: media
   * clasificacion, con las 22 de Copernicus Marine, las 12 de EMODnet y las 8
   * escritas a mano fuera de ella. Ahora el catalogo es uno y la comprobacion
   * cubre las sesenta. Lo que protege es que una capa nueva no pueda quedarse
   * sin grupo por despiste -- entonces no aparece en el panel y es
   * indistinguible de no existir.
   */
  try {
    const RUNTIME = ['live', 'suppressed_live'];
    ctx.loadMarine(rd('marine_layers.json'));
    ctx.loadEmodnet(rd('emodnet_layers.json'));
    const cat = ctx.lpBuild();
    const errs = [];
    if (cat.length < 50) { errs.push('solo ' + cat.length + ' capas en el catalogo'); }

    const seen = {}, dup = [];
    cat.forEach(e => { if (seen[e.id]) { dup.push(e.id); } seen[e.id] = 1; });
    if (dup.length) { errs.push('repetidas: ' + dup.join()); }

    /* Los dos ejes, completos: una clave de grupo desconocida no se dibuja. */
    const badT = cat.filter(e => ctx.LP_THEMES.indexOf(e.theme) < 0);
    const badS = cat.filter(e => ctx.LP_SOURCES.indexOf(e.source) < 0);
    if (badT.length) { errs.push('tema desconocido: ' + badT.map(e => e.id + '=' + e.theme).join()); }
    if (badS.length) { errs.push('fuente desconocida: ' + badS.map(e => e.id + '=' + e.source).join()); }

    /* Toda capa dibujada en el mapa tiene que estar en el catalogo. */
    const loose = Object.keys(ctx.layers)
      .filter(k => !seen[k] && RUNTIME.indexOf(k) < 0);
    if (loose.length) { errs.push('en el mapa pero no en el panel: ' + loose.join()); }

    /* LA FUENTE QUE DICE LA ETIQUETA TIENE QUE SER LA FUENTE DE VERDAD.
     *
     * Agrupar por fuente destapo que las isobatas se anunciaban como
     * «(HELCOM)» cuando son nuestras sobre el DTM de EMODnet -- y la capa de
     * contornos de HELCOM esta descartada A PROPOSITO porque prohibe uso
     * comercial. Acreditar a quien no es, en una capa que se descarto por su
     * licencia, es el error mas caro que puede tener una etiqueta.
     */
    const CREDIT = { helcom: 'HELCOM', emodnet: 'EMODnet', osm: 'OpenStreetMap',
                     fintraffic: 'Fintraffic', gfw: 'Global Fishing Watch',
                     vayla: 'Väylävirasto', aishub: 'AISHub' };
    const miscredit = cat.filter(e => {
      const n = String(e.name);
      return Object.keys(CREDIT).some(k => k !== e.source
        && n.indexOf(CREDIT[k]) >= 0
        && n.indexOf(CREDIT[e.source] || '\u0000') < 0);
    });
    if (miscredit.length) {
      errs.push('acredita a otra fuente: '
                + miscredit.map(e => e.id + ' = ' + e.name).join(' / '));
    }

    /* NINGUNA FILA VACIA. Una capa que el build no produjo tiene que salir
     * apagada y con su razon, no como un hueco: un hueco es indistinguible de
     * que la capa no exista. */
    const vacias = cat.filter(e => e.row && !String(e.row()).trim());
    if (vacias.length) { errs.push('fila vacia: ' + vacias.map(e => e.id).join()); }

    /* Y toda entrada tiene nombre: una fila sin nombre no se puede buscar. */
    const noname = cat.filter(e => !e.name || !String(e.name).trim());
    if (noname.length) { errs.push('sin nombre: ' + noname.map(e => e.id).join()); }

    /* Los dos ejes tienen que repartir de verdad, no dejar un cajon con todo.
     * Si un grupo se lleva mas de la mitad, agrupar no ha servido de nada. */
    ['theme', 'source'].forEach(ax => {
      const c = {};
      cat.forEach(e => { c[e[ax]] = (c[e[ax]] || 0) + 1; });
      const top = Math.max.apply(null, Object.keys(c).map(k => c[k]));
      if (top > cat.length / 2) {
        errs.push('eje ' + ax + ': un grupo se lleva ' + top + ' de ' + cat.length);
      }
      if (Object.keys(c).length < 4) {
        errs.push('eje ' + ax + ': solo ' + Object.keys(c).length + ' grupos');
      }
    });

    /* TRES CLICS. Pestana -> grupo -> capa. Se comprueba sobre el HTML real:
     * cada capa tiene que estar dentro de UN <details>, no de dos anidados. */
    ctx.LP.q = ''; ctx.LP.axis = 'theme';
    const html = (function () {
      const box = ctx.document.getElementById('layer-panel');
      ctx.renderLayerPanel();
      return String(box.innerHTML || '');
    })();
    const depth = (html.match(/<details/g) || []).length;
    if (!depth) {
      errs.push('el panel no produce grupos plegables (html ' + html.length + ' B)');
      if (process.env.SMOKE_DEBUG) { console.log('    [dbg] html=', html.slice(0, 300)); }
    }

    /* Y el buscador: dos letras tienen que encontrar la capa por su nombre. */
    ctx.LP.q = 'cable';
    const hits = cat.filter(ctx.lpMatch);
    ctx.LP.q = '';
    if (!hits.length) { errs.push('el buscador no encuentra «cable»'); }

    if (errs.length) { bad += 1; console.log('  FALLO catalogo de capas: ' + errs.join(' · ')); }
    else {
      const th = {}, sr = {};
      cat.forEach(e => { th[e.theme] = 1; sr[e.source] = 1; });
      console.log('  ok    catalogo de capas (' + cat.length + ' capas, '
                  + Object.keys(th).length + ' temas y ' + Object.keys(sr).length
                  + ' fuentes, ' + depth + ' grupos plegables, «cable» -> '
                  + hits.length + ')');
    }
  } catch (e) { bad += 1; console.log('  FALLO catalogo de capas -> ' + e.message); }

  /* Que el raster de profundidad caiga DONDE DICE. Leaflet estira un
   * ImageOverlay linealmente sobre Mercator, y la primera version espaciaba
   * las filas en latitud: hasta 66 km de error en el centro del Baltico y
   * cero en los bordes, que por fuera parece «la capa no cuadra». Se compara
   * contra depth_grid.json, construido por otro camino, y se exige ademas
   * que el mapeo erroneo puntue claramente peor: si los dos empatan, la
   * comprobacion no distingue nada y no vale. */
  try {
    const out = require('child_process').execSync(
      'python3 -m custody.depthmap --verify ' + path.join(DATA, 'depth_map.png')
      + ' ' + path.join(DATA, 'depth_grid.json'),
      { cwd: path.join(__dirname, '..'), encoding: 'utf8' });
    const v = JSON.parse(out);
    const good = v['mercator'].pct, wrong = v['linear-in-latitude'].pct;
    if (good < 99 || good - wrong < 3) {
      bad += 1;
      console.log('  FALLO registro del raster de profundidad: mercator '
                  + good + '%, lineal ' + wrong + '% (se esperaba >=99 y una'
                  + ' diferencia clara)');
    } else {
      console.log('  ok    registro del raster de profundidad (' + good + '% sobre '
                  + v['mercator'].samples + ' muestras; el mapeo erroneo da '
                  + wrong + '%)');
    }
  } catch (e) { bad += 1; console.log('  FALLO registro del raster -> ' + e.message); }

  /* La paleta vive DOS veces: en custody/depthmap.py, que pinta el PNG, y en
   * viewer/depthmap.js, que pinta la leyenda y el respaldo en canvas. Si se
   * separan, la leyenda miente sobre la imagen. Esto las ata. */
  try {
    const py = require('fs').readFileSync('../custody/depthmap.py', 'utf8');
    const rows = [...py.matchAll(/\(\s*([\d.e+]+),\s*\((\d+), (\d+), (\d+)\)/g)]
      .map(m => [Number(m[1]), [+m[2], +m[3], +m[4]]]);
    const js = ctx.DEPTH_BANDS.map(b => [b.max, b.c]);
    const same = rows.length === js.length && rows.every((r, i) =>
      (r[0] > 1e8 ? js[i][0] > 1e8 : r[0] === js[i][0])
      && r[1].join() === js[i][1].join());
    if (!same) {
      bad += 1;
      console.log('  FALLO paleta descuadrada entre depthmap.py y depthmap.js');
    } else {
      console.log('  ok    paleta unica py/js (' + rows.length + ' bandas iguales)');
    }
  } catch (e) { bad += 1; console.log('  FALLO paleta py/js -> ' + e.message); }

  /* La paleta de profundidad. La queja original era que la escala oficial
   * gasta medio espectro en profundidades que en el Baltico no existen, asi
   * que lo que hay que comprobar es justo eso: que NINGUNA banda se quede
   * vacia y que ninguna se coma el mapa. Si alguien mueve un corte y rompe
   * el reparto, esto lo caza. */
  try {
    const g = rd('depth_grid.json');
    if (g && Array.isArray(ctx.DEPTH_BANDS)) {
      const sea = g.vals.filter(v => v !== null && v > 0);
      const n = ctx.DEPTH_BANDS.map(b => 0);
      sea.forEach(d => {
        for (let i = 0; i < ctx.DEPTH_BANDS.length; i += 1) {
          if (d < ctx.DEPTH_BANDS[i].max) { n[i] += 1; return; }
        }
      });
      const sh = n.map(k => 100 * k / sea.length);
      const dead = sh.filter(p => p < 1).length;
      const hog = Math.max.apply(null, sh);
      const land = g.vals.length - sea.length;
      if (dead || hog > 30 || land < sea.length) {
        bad += 1;
        console.log('  FALLO paleta de profundidad: ' + dead + ' bandas <1%, mayor '
                    + hog.toFixed(1) + '%, tierra ' + land);
      } else {
        console.log('  ok    paleta de profundidad (9 bandas, '
                    + Math.min.apply(null, sh).toFixed(1) + '-' + hog.toFixed(1)
                    + '% cada una, ' + land + ' celdas de tierra sin pintar)');
      }
    }
  } catch (e) { bad += 1; console.log('  FALLO paleta de profundidad -> ' + e.message); }

  /* Y el filtrado en caliente, que es logica pura y se puede comprobar */
  try {
    const n0 = ctx.visibleAlertFeatures().length;
    ctx.OPS.minScore = 999;
    const n1 = ctx.visibleAlertFeatures().length;
    ctx.OPS.minScore = 0;
    if (!(n0 > 0 && n1 === 0)) {
      bad += 1; console.log('  FALLO filtro minScore: ' + n0 + ' -> ' + n1);
    } else { console.log('  ok    filtros en caliente (' + n0 + ' -> 0)'); }
  } catch (e) { bad += 1; console.log('  FALLO filtros -> ' + e.message); }
} else {
  console.log('  --    sin data/manifest.json: ejecuta build.py para el test de render');
}

/* Las funciones que app.js necesita resueltas en el momento de arrancar */
for (const fn of ['loadDepth', 'shipIcon', 'headingOf', 'vesselCard', 'renderSources',
                  'renderSourceStrip', 'explainFor', 'shipTypeText', 't']) {
  if (typeof ctx[fn] !== 'function') { bad += 1; console.log('  FALTA función global: ' + fn); }
}
console.log(bad ? '\n=== ' + bad + ' FALLOS ===' : '\n=== carga limpia ===');
process.exit(bad ? 1 : 0);
