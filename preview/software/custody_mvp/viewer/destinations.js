/* destinations.js - de lo que el buque DICE a donde eso esta en el mapa.
 *
 * El mensaje AIS 5 lleva un campo `destination` de 20 caracteres que teclea
 * la tripulacion. No es un identificador: es texto libre. En el golfo
 * aparecen las tres formas a la vez —`RULED`, `RU LED`, `ST PETERSBURG`— mas
 * cosas que no son un puerto en absoluto, como `FOR ORDER` o `HARBOUR
 * ASSISTANCE`.
 *
 * Esta tabla es CURADA A MANO para los puertos del Baltico que de verdad
 * aparecen en el trafico grabado. No se resuelve por aproximacion de cadenas
 * contra los nombres de OSM: esos son en su mayoria puertos deportivos
 * («vierasvenesatama») y emparejarlos mandaria un petrolero a un pantalan de
 * recreo. Lo que no este en la tabla se declara SIN RESOLVER y se dice en
 * pantalla, que es mejor que una flecha apuntando a un sitio inventado.
 *
 * Coordenadas aproximadas al area portuaria, suficientes para un rumbo a
 * decenas de millas; no son puntos de atraque.
 */
'use strict';

var PORTS = [
  /* locode, nombre, lon, lat, alias adicionales */
  ['FIHEL', 'Helsinki',        24.955, 60.167, ['HELSINKI', 'HKI', 'FI HEL']],
  ['FIKTK', 'Kotka',           26.950, 60.462, ['KOTKA', 'FI KTK']],
  ['FIHMN', 'Hamina',          27.180, 60.563, ['HAMINA', 'FI HMN']],
  ['FITKU', 'Turku',           22.228, 60.434, ['TURKU', 'ABO', 'FI TKU']],
  ['FINLI', 'Naantali',        22.020, 60.468, ['NAANTALI', 'FI NLI']],
  ['FIPRV', 'Porvoo / Skoldvik', 25.553, 60.300, ['PORVOO', 'SKOLDVIK', 'KILPILAHTI', 'FI PRV']],
  ['FIRAU', 'Rauma',           21.503, 61.131, ['RAUMA', 'FI RAU']],
  ['FIPOR', 'Pori',            21.580, 61.600, ['PORI', 'FI POR']],
  ['FIKOK', 'Kokkola',         23.015, 63.850, ['KOKKOLA', 'FI KOK']],
  ['FIOUL', 'Oulu',            25.420, 65.030, ['OULU', 'FI OUL']],
  ['FIINK', 'Inkoo',           24.010, 60.045, ['INKOO', 'INGA', 'FI INK']],
  ['FIHKO', 'Hanko',           22.960, 59.823, ['HANKO', 'HANGO', 'FI HKO']],
  ['FIVAL', 'Valko / Loviisa', 26.250, 60.420, ['VALKO', 'LOVIISA', 'FI VAL']],
  ['FIKAS', 'Kasnas',          22.400, 59.930, ['KASNAS']],
  ['FIEUR', 'Eurajoki / Olkiluoto', 21.440, 61.240, ['EURAJOKI', 'OLKILUOTO']],
  ['FILPP', 'Lappeenranta',    28.180, 61.060, ['LAPPEENRANTA']],
  ['FIMHQ', 'Mariehamn',       19.940, 60.097, ['MARIEHAMN', 'FI MHQ']],
  ['EETLL', 'Tallinn',         24.768, 59.445, ['TALLINN', 'EE TLL']],
  ['EEMUG', 'Muuga',           25.000, 59.500, ['MUUGA', 'EE MUG']],
  ['EEPAL', 'Paldiski',        24.050, 59.350, ['PALDISKI', 'EE PAL']],
  ['EESLM', 'Sillamae',        27.740, 59.420, ['SILLAMAE', 'EE SLM']],
  ['EEKND', 'Kunda',           26.540, 59.520, ['KUNDA', 'EE KND']],
  ['EEPRN', 'Parnu',           24.490, 58.385, ['PARNU', 'EE PRN']],
  ['EEHUN', 'Hundipea',        24.760, 59.460, ['HUNDIPEA']],
  ['RULED', 'St Petersburg',   30.250, 59.900, ['ST PETERSBURG', 'SAINT PETERSBURG',
                                                'PETERSBURG', 'RU LED', 'SPB']],
  ['RUULU', 'Ust-Luga',        28.270, 59.670, ['UST LUGA', 'UST-LUGA', 'USTLUGA', 'RU ULU']],
  ['RUPRI', 'Primorsk',        28.720, 60.350, ['PRIMORSK', 'RU PRI']],
  ['RUVYS', 'Vysotsk',         28.570, 60.630, ['VYSOTSK', 'RU VYS', 'VYSOCK']],
  ['RUVYG', 'Vyborg',          28.740, 60.710, ['VYBORG', 'RU VYG']],
  ['RUKGD', 'Kaliningrad',     20.500, 54.700, ['KALININGRAD', 'RU KGD', 'BALTIYSK']],
  ['LVRIX', 'Riga',            24.080, 56.970, ['RIGA', 'LV RIX']],
  ['LVVNT', 'Ventspils',       21.550, 57.400, ['VENTSPILS', 'LV VNT']],
  ['LVLPX', 'Liepaja',         21.010, 56.520, ['LIEPAJA', 'LV LPX']],
  ['LTKLJ', 'Klaipeda',        21.130, 55.700, ['KLAIPEDA', 'LT KLJ']],
  ['PLGDN', 'Gdansk',          18.670, 54.400, ['GDANSK', 'PL GDN']],
  ['PLGDY', 'Gdynia',          18.540, 54.535, ['GDYNIA', 'PL GDY']],
  ['PLSZZ', 'Szczecin',        14.600, 53.430, ['SZCZECIN', 'SWINOUJSCIE', 'PL SZZ']],
  ['SESTO', 'Stockholm',       18.075, 59.320, ['STOCKHOLM', 'SE STO']],
  ['SEGOT', 'Goteborg',        11.900, 57.700, ['GOTEBORG', 'GOTHENBURG', 'SE GOT']],
  ['SENRK', 'Norrkoping',      16.200, 58.590, ['NORRKOPING']],
  ['SELUL', 'Lulea',           22.160, 65.580, ['LULEA', 'SE LUL']],
  ['DKCPH', 'Copenhagen',      12.600, 55.700, ['COPENHAGEN', 'KOBENHAVN', 'DK CPH']],
  ['DEROS', 'Rostock',         12.100, 54.150, ['ROSTOCK', 'DE ROS']],
  ['DELBC', 'Lubeck',          10.870, 53.890, ['LUBECK', 'TRAVEMUNDE', 'DE LBC']],
  ['DEKEL', 'Kiel',            10.140, 54.330, ['KIEL', 'DE KEL']],
  ['DEHAM', 'Hamburg',          9.950, 53.540, ['HAMBURG', 'DE HAM']],
  ['NLRTM', 'Rotterdam',        4.400, 51.920, ['ROTTERDAM', 'NL RTM']],
  ['BEANR', 'Antwerp',          4.330, 51.280, ['ANTWERP', 'ANTWERPEN', 'BE ANR']],
  ['DKSKA', 'Skagen',          10.590, 57.720, ['SKAGEN', 'SKAW', 'DK SKA']],
  ['EGPSD', 'Port Said',       32.310, 31.260, ['PORT SAID', 'EG PSD']]
];

/* Textos que NO son un destino y conviene no intentar resolver. */
var NON_DESTINATIONS = [
  'FOR ORDER', 'FOR ORDERS', 'ORDERS', 'NOORDERS', 'NO DESTINATION',
  'HARBOUR ASSISTANCE', 'PILOT STATION', 'FISHING', 'SAR', 'LOCAL',
  'UNKNOWN', 'N/A', 'NIL', 'TBN', 'TBA', 'SEA', 'AT SEA', 'ANCHORAGE'
];

var _PORT_IDX = null;
function portIndex() {
  if (_PORT_IDX) { return _PORT_IDX; }
  _PORT_IDX = {};
  PORTS.forEach(function (p) {
    var rec = { locode: p[0], name: p[1], lon: p[2], lat: p[3] };
    _PORT_IDX[p[0]] = rec;
    (p[4] || []).forEach(function (a) { _PORT_IDX[normDest(a)] = rec; });
  });
  return _PORT_IDX;
}

function normDest(s) {
  return String(s || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
}

/* Devuelve {port, via} o null. `via` dice COMO se resolvio, porque no es lo
 * mismo un LOCODE exacto que un prefijo: lo segundo puede equivocarse y el
 * visor lo marca. */
function resolveDestination(raw) {
  if (!raw) { return null; }
  var up = String(raw).toUpperCase().trim();
  for (var i = 0; i < NON_DESTINATIONS.length; i += 1) {
    if (up.indexOf(NON_DESTINATIONS[i]) >= 0) {
      return { port: null, via: 'not-a-destination', text: raw };
    }
  }
  var idx = portIndex();
  var n = normDest(up);
  if (idx[n]) { return { port: idx[n], via: 'exact', text: raw }; }
  /* Muchos destinos son «PUERTO VIA ALGO» o «PUERTO>OTRO». Se parte y se
   * prueba el primer trozo, que es a donde va ahora. */
  /* `EEVAN<>FIHEL` es notacion de linea de ferri: el primer trozo vale. */
  var head = normDest(up.split(/<>|VIA|>|->|,|\//)[0]);
  if (head && idx[head]) { return { port: idx[head], via: 'prefix', text: raw }; }
  var keys = Object.keys(idx);
  for (var k = 0; k < keys.length; k += 1) {
    if (keys[k].length >= 5 && n.indexOf(keys[k]) === 0) {
      return { port: idx[keys[k]], via: 'startswith', text: raw };
    }
  }
  return { port: null, via: 'unresolved', text: raw };
}

/* Rumbo inicial de loxodroma, en grados verdaderos. */
function bearingTo(lon1, lat1, lon2, lat2) {
  var p1 = lat1 * Math.PI / 180, p2 = lat2 * Math.PI / 180;
  var dl = (lon2 - lon1) * Math.PI / 180;
  var y = Math.sin(dl) * Math.cos(p2);
  var x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}

function angleGap(a, b) {
  var d = Math.abs(a - b) % 360;
  return d > 180 ? 360 - d : d;
}
