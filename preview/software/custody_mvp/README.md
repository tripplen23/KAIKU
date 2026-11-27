# custody_mvp — developer notes

> **Single source of truth.** Anything about *running, using or configuring* this tool
> lives in **[../MANUAL.md](../MANUAL.md)** and only there. This file covers architecture,
> decisions and verification evidence — the things a reader of the code needs and a user
> does not. If a fact appears in both, MANUAL.md wins.

| Looking for | Go to |
|---|---|
| Qué cambió y por qué | [../CHANGELOG.md](../CHANGELOG.md) |
| Start / stop / rebuild | [../MANUAL.md §1](../MANUAL.md) |
| Credentials and CDSE account | [../MANUAL.md §18](../MANUAL.md) |
| What the interface does | [../MANUAL.md, parte II](../MANUAL.md) |
| Vessel size, photos, sanctions | [../MANUAL.md §20](../MANUAL.md) |
| Wrecks, submarines, military areas | [../MANUAL.md §21](../MANUAL.md) |
| SAR ship detection (CFAR) | [../MANUAL.md §22](../MANUAL.md) |
| Replaying the cable incidents | [../MANUAL.md §23](../MANUAL.md) |
| Alcance y cobertura del AIS | [../MANUAL.md §4b](../MANUAL.md) |
| Vessel situation, one click | [../MANUAL.md §8](../MANUAL.md) |
| Declared route and divergence | [../MANUAL.md §9](../MANUAL.md) |
| Data sources and licences | Sources tab in the viewer, and [../MANUAL.md §27](../MANUAL.md) |
| Why a threshold is what it is | this file, §Indicadores |
| What was measured vs assumed | this file, §Degradación controlada |

## Arranque

Un solo entrypoint para toda la pila:

```bash
cd ..            # software/
./custody.sh up        # grabador + build si falta + visor
./custody.sh status    # qué corre, cuánto dato hay, si hay credenciales
./custody.sh down      # para visor y grabador
./custody.sh build     # solo reconstruir capas
```

Detalle y variantes: [../MANUAL.md §1](../MANUAL.md).

## Qué fuentes entran y qué hace cada una

> Referencia canónica: la pestaña **Sources** del visor, que además marca qué es Programa
> Espacial de la UE y qué no. Lo de aquí abajo es la vista de implementación.

| # | Fuente | Acceso | Qué aporta | Licencia / atribución obligatoria |
|---|---|---|---|---|
| 1 | **Fintraffic Digitraffic AIS** | almacén local de `../ais_recorder` (REST `/api/ais/v1/locations`) | trazas, velocidad, rumbo, proa, estado de navegación, metadatos de buque | `Fintraffic / digitraffic.fi, licence CC 4.0 BY` |
| 2 | **OpenStreetMap / Overpass** | `POST https://overpass-api.de/api/interpreter` | corredores submarinos (cables de potencia, telecom, gasoductos) y máscara de puertos/fondeaderos | `(c) OpenStreetMap contributors, ODbL 1.0` |
| 3 | **EMODnet Bathymetry WCS** | `GET https://ows.emodnet-bathymetry.eu/wcs` (`emodnet__mean`, GeoTIFF float32) | rejilla de profundidad, isobatas, **y la línea de costa** | `EMODnet Bathymetry Consortium — EMODnet Digital Bathymetry (DTM)` |
| 4 | **EMODnet Bathymetry REST** | `GET https://rest.emodnet-bathymetry.eu/depth_sample` | profundidad puntual **con procedencia** (qué DTM o campaña, con URL de metadatos) | ídem |
| 5 | **Copernicus Data Space (CDSE) STAC** | `POST https://stac.dataspace.copernicus.eu/v1/search` | catálogo Sentinel-1 GRD, footprints exactos, quicklooks públicos | `Contains modified Copernicus Sentinel data` |
| 6 | **Väylävirasto WFS** | `GET https://avoinapi.vaylapilvi.fi/vaylatiedot/ows` (`vesivaylatiedot:rajoitusalue_a_uusi`) | áreas de restricción a la navegación, incluida **la prohibición de fondeo** con su `diaarinumero` | `Väylävirasto, datos abiertos, CC BY 4.0` |

Dos correcciones de iteración 01 que este código incorpora y que, si se olvidan, rompen el
pipeline en silencio:

- **EMODnet Human Activities (cables) no cubre Finlandia** — comprobado en
  `canal/iteracion_01/04_coo.md` H3. La geometría de corredores viene de OSM.
- El endpoint STAC correcto es `stac.dataspace.copernicus.eu/v1/search`, y **Digitraffic
  devuelve 406 sin `Accept-Encoding: gzip`**. `custody/net.py` lo fija para todas las peticiones.
- Añadido aquí: **Overpass devuelve 406 con el `User-Agent` por defecto de urllib.**

---

## Arquitectura

```
build.py                 orquestador. Un paso por capa. Escribe viewer/data/*.geojson
selftest.py              verificación end-to-end sin navegador
custody/
  net.py                 HTTP con gzip, User-Agent, backoff+jitter y caché por sha256
  creds.py               lectura de secrets.env. Entorno > fichero. Nunca vuelca contenido
  geo.py                 haversine, distancia punto-polilínea, índice de segmentos en rejilla,
                         máscara de polígonos, recorte Cohen-Sutherland
  tiff.py                lector GeoTIFF float32 sin comprimir (tiles y strips). ~130 líneas.
                         Evita pyarrow/rasterio/GDAL: 0 dependencias
  ais.py                 carga del almacén NDJSON.gz, normaliza centinelas AIS, ventanas de
                         cobertura a partir del log de polls
  corridors.py           Overpass -> GeoJSON + clasificación + máscara de puerto
  bathymetry.py          WCS -> rejilla, marching squares -> isobatas y costa, REST -> procedencia
  sentinel.py            STAC, quicklook público, y descarga OAuth2 del GRD (requiere cuenta)
  vayla.py               WFS de restricciones a la navegación y máscara de prohibición de fondeo
  sardetect.py           deteccion de buques en SAR por CA-CFAR. Lector GeoTIFF uint16
                         multimuestra + umbral local + agrupado + georreferencia. Validado
                         contra una deteccion publicada por Skylight: 55 m de diferencia
  authorities.py         registro de quien prohibe que en cada pais riberenyo. FI por
                         Vaylavirasto; EE/DE/LT/LV por los planes de ordenacion maritima
                         de HELCOM; SE/PL/DK/RU declarados como hueco con su motivo.
                         Anyadir un pais es una fila
  seabed.py              EMODnet Human Activities: 693 pecios (3 submarinos, entre ellos el
                         U-26 de 1915), 24 áreas de defensa nacional FI/EE y 3 vertederos de
                         munición. Las alertas se ANOTAN con este contexto, nunca se suprimen
  gfw.py                 Global Fishing Watch v3: eventos de comportamiento (GAP, ENCOUNTER,
                         LOITERING, PORT_VISIT) y rejillas 4wings (presencia, pesca, SAR).
                         Segunda opinión independiente, no AIS crudo
  vesselinfo.py          dossier por buque. Eslora/manga/calado del propio AIS (A+B, C+D del
                         mensaje 5, sin red); sanciones OFAC SDN y lista consolidada de la UE
                         por IMO/MMSI; foto y particulares de Wikidata/Commons. Tabla MID
                         completa de la UIT: única fuente de bandera del proyecto
  indicators.py          IND-01..IND-05, umbrales, justificación y mapeo al catálogo del CTO
test_indicators.py       31 pruebas unitarias de los indicadores (trazas sintéticas, sin red)
viewer/
  index.html app.js style.css
  whatsnew.js            recorrido de novedades de la INTERFAZ. Cada paso lleva al usuario
                         a donde esta el cambio. Lo que no se pueda señalar con el dedo
                         va en CHANGELOG.md, no aqui
  destinations.js        el campo `destination` del AIS -> puerto en el mapa. Tabla curada
                         de 48 puertos del Báltico; resuelve el 53% de las trazas y declara
                         el resto sin resolver en vez de adivinar por parecido de nombre
  server.py              servidor del visor: multihilo + proxy con caché en disco de las
                         teselas de Planetary Computer. Lo lanza serve.sh. Medido 1558 ms
                         en frío contra 139 ms en caliente sobre cuatro teselas
  smoke.js               carga los scripts en el orden de index.html con DOM y Leaflet de
                         juguete, valida las claves i18n y ejecuta el render con los datos
                         del último build. `node smoke.js`. Atrapa los dos fallos que ya se
                         han colado: orden de carga y referencia a un id inexistente
  vendor/leaflet/        Leaflet 1.9.4 (js, css, images). Sin CDN
  data/                  salida de build.py. Se regenera, no se edita
cache/                   caché de red. Borrable. No se versiona
```

### Decisiones que merecen defensa

**Lector de GeoTIFF propio en lugar de `rasterio`/GDAL.** El único raster que se lee es el que
devuelve EMODnet WCS: float32, 1 banda, sin comprimir. Son 130 líneas de `struct`. La alternativa
son ~100 MB de ruedas, un venv (este sistema es PEP-668) y una dependencia binaria que hay que
instalar en el portátil del hackatón. `tiff.py` lanza `NotImplementedError` ante cualquier
combinación fuera de alcance en vez de devolver números silenciosamente mal.

**Costa derivada de la propia batimetría.** El visor tiene que funcionar sin red, y sin costa un
mapa de cables es ilegible. En vez de añadir un basemap o un shapefile de terceros, la costa sale
de contornear la máscara tierra/agua de la rejilla EMODnet que ya se ha descargado. Coherente con
la batimetría que se muestra y coste marginal cero.

**Leaflet vendorizado, no CDN.** El wifi de un evento no es una dependencia aceptable. Las dos
únicas capas que salen a la red (basemap OSM y batimetría WMS de EMODnet) están etiquetadas y
**apagadas por defecto**.

**`corridors_trunk` / `corridors_other` en ficheros separados.** Los 5.640 elementos submarinos del
AOI son 2,4 MB y saturan el render; los 31 troncales con nombre son 88 kB. `trunk` se define por
el dato (tiene nombre y mide ≥ 5 km), no por una lista blanca de nombres.

**Geometría recortada al AOI.** Overpass devuelve la vía completa: Nord Stream llega a Alemania y
Fenno-Skan a Suecia. Sin recorte el encuadre inicial del visor es el Báltico entero.

---

## Indicadores

Definidos en `custody/indicators.py`. **Los umbrales son INICIALES y NO están calibrados**: no
existe en abierto AIS histórico del golfo para diciembre de 2024, así que no hay un conjunto
etiquetado contra el que ajustar (comprobado en `canal/iteracion_01/01_systems_engineer.md` §5).
Cada uno lleva su justificación física en `JUSTIFICATION` y su confianza.

| ID | P del CTO | Qué mide | Umbral inicial | Confianza |
|---|---|---|---|---|
| **IND-01** | P3 + P2 + P1 | velocidad baja sostenida sobre corredor | p10 y p90 de `sog` dentro de **[1, 5] kn** durante **≥ 30 min**, ≤ 2 NM de un corredor trunk, `navStat=0` en ≥ 80 % de los fixes, desplazamiento neto ≥ 0,5 NM, profundidad ≥ 10 m, fuera de máscara de puerto. Marca `under_power_p1` si p10 ≥ 2,5 kn (P1: la deriva pasiva no explica el movimiento) y `within_500m_buffer` (P2) | Media-Baja |
| **IND-02** | P4 | **sesgo unilateral** de COG−HDG | mediana de `heading − cog` **con signo**, mismo signo en ≥ 90 % de la ventana, \|mediana\| ≥ 8°, `sog` ≥ 3 kn, ≥ 20 min. > 90° se reclasifica como fallo de sensor o marcha atrás y puntúa la mitad | Media |
| **IND-03** | — | loitering | `sog` < 1 kn durante ≥ 60 min, desplazamiento neto < 0,5 NM, `navStat` ∉ {1, 5}, fuera de máscara de puerto **y a > 1 NM de la costa**. **Es EXPOSICIÓN, no alerta** | Alta en cómputo, nula en discriminación hoy |
| **IND-04** | P6 | hueco de AIS | `timestampExternal` deja de avanzar ≥ 30 min **dentro de una ventana de cobertura del log de polls**. Distingue hueco cerrado (vuelve) de abierto (sigue mudo), y degrada el abierto a 0,15 si el último fix está a < 5 NM del borde del AOI | Alta en detección, Baja en intención |
| **IND-05** | P2 + batimetría | proximidad a corredor ponderada por profundidad | ≤ 1 NM de un corredor trunk **y** profundidad en [10, 80] m, con tier marcado a 500 m. **Es EXPOSICIÓN, no alerta** | Alta en física y en el dato |
| **IND-06** | P8 | encuentro barco a barco | < 500 m, ambos `sog` < 3 kn, > 30 min, `navStat` ∉ {1, 5}, fuera de máscara de puerto **y a > 1 NM de la costa**. **Es EXPOSICIÓN, no alerta** | Alta en cómputo, nula en discriminación hoy |

**Por qué IND-03 tampoco es una alerta, con el número.** De 63 episodios, la máscara de puerto
suprime 28 y el criterio de 1 NM otros 25; de las 10 salidas restantes, **8 son lanchas de práctico
amarradas** en Harmaja (24,974 E / 60,105 N) y Emäsalo (26,445 E / 60,275 N), y las otras 2 son
**transpondedores AIS de prueba fijos** — `FURUNOP` y `NAVI TEST`, con **4 y 3 metros** de
desplazamiento neto en una hora. Falsa alarma 10/10, misma causa que IND-06.

**Por qué IND-06 tampoco es una alerta, con el número.** 61 episodios de pareja cumplen el criterio
cinemático; la máscara de puerto y fondeadero de OSM suprime 29; el criterio geométrico de 1 NM de
costa suprime 17 más; quedan **15, y los 15 son grupos de lanchas de práctico amarradas en sus
bases** (Harmaja a 2,6 km
de la costa, Emäsalo a 7,5 km) — «en la mar» para cualquier criterio geométrico, y benignos.
**Falsa alarma 15/15.** No se filtra por `shipType=50`: el tipo es autodeclarado y falsificable, y
filtrar por él es exactamente la puerta que usaría quien quisiera pasar desapercibido. IND-06
vuelve a ser alerta cuando exista la máscara oficial de zonas de espera y estaciones de práctico,
que no está publicada. Esto es, además, la tasa de falsa alarma medida del `AtSeaEncounter` que
EMSA opera gratis desde 2016 sobre el tráfico real del golfo.

**Lo que queda.** De seis indicadores conductuales implementados desde el estado del arte, **tres
hay que degradar a exposición** porque su flujo de alertas lo domina infraestructura fija benigna.
Los tres que sobreviven como alerta —IND-01, IND-02, IND-04— se apoyan en **física** (banda de
velocidad sobre el corredor, sesgo unilateral de proa) y en **continuidad del dato** (hueco de AIS
corregido por cobertura), no en patrones de «loitering» o «encuentro».

**Por qué IND-02 no es un umbral de 20° instantáneo.** El CTO midió que `|COG−HDG| > 20°` con
`sog ≥ 2 kn` dispara sobre el **4,12 %** de 5.141 fixes en movimiento (`02_cto.md` A.3): inusable
como alarma. Lo que se mide es el **sesgo**, no la divergencia. Un buque que arrastra algo por
una banda guiña siempre hacia el mismo lado; la deriva por viento cambia de signo cuando el
viento rota. La prueba unitaria `IND-02 · 25 grados alternando signo` es exactamente el caso que
el umbral absoluto marcaba mal y este no marca.

**Lo que NO está implementado del catálogo del CTO**, y va declarado en
`indicators.NOT_IMPLEMENTED` y en `alerts.geojson`:

| P | Qué falta | Por qué |
|---|---|---|
| **P5** | invariancia del signo de COG−HDG frente al viento | exige ERA5 o CMEMS WIND horario. **Es el discriminador real de P4**: sin él, IND-02 no separa arrastre de deriva por viento sostenido |
| **P7** | residuo de deriva contra corriente (umbral 3σ = 1,58 kn) | exige CMEMS PHY 003_006 |
| **P8** | encuentro barco a barco | implementable ya con los datos actuales; no entra en esta iteración |
| **P9** | contrafáctico de daño | bloqueado: t₁ (hora del fallo del activo) no es dato abierto |
| **P10, P11, P12** | grafo de rutas, autoencoder, cambio de calado | coste alto / valor no demostrado / campo declarado |

**Por qué IND-05 no es una alerta.** En la pasada en que se tomó la decisión, 71 de 75 "alertas" eran
ferries de línea Helsinki–Tallinn cruzando cables: cruzarlos es su ruta. Una capa de alertas dominada por
tráfico regular de pasaje no le sirve a un operador. IND-05 pondera la puntuación compuesta y se
pinta en su propia capa, en ámbar, separada de las alertas.

**Tres trampas de interfaz implementadas a propósito.** Omitir cualquiera de ellas produce cero
alertas o todas a la vez, sin aviso:

1. *Un buque nunca desaparece del feed REST.* El endpoint sirve su último fix durante ~24 h.
   "Perdió AIS" se detecta porque `timestampExternal` deja de avanzar, no porque el MMSI deje de
   aparecer. Se cumple porque el cargador deduplica por `(mmsi, timestampExternal)`.
2. *Un hueco en los datos no es un hueco en el AIS.* IND-04 solo considera huecos íntegramente
   contenidos en una ventana de polling continuo reconstruida del `polllog`.
3. *El arranque en frío trae un fix de hasta 24 h de antigüedad por buque.* El salto entre ese fix
   y el siguiente no es comportamiento. Toda ventana exige gap interno ≤ 600 s, y las trazas del
   mapa se parten en ese mismo umbral.

Cada alerta lleva `evidence` con las claves `(mmsi, timestampExternal)` de los fixes que la
sostienen, los ficheros de origen, la duración, el corredor y su `osm_id`, y la profundidad con su
**DTM de procedencia y la URL de sus metadatos**. Eso es lo que permite rehacer el cálculo desde
el dato crudo seis meses después.

---

## Sentinel-1: qué se consigue y qué no

> Cómo crear la cuenta CDSE y dónde van las credenciales: [../MANUAL.md §18](../MANUAL.md). **Las credenciales ya no van en JSON**: `secrets.env`, formato `clave=valor`, permisos 600, en `.gitignore`.

Sin cuenta CDSE (verificado 2026-11-09):

- catálogo STAC: **sí**, sin autenticación;
- footprint exacto de cada escena: **sí**;
- `thumbnail` (quicklook PNG ~297×191, servido por `datahub.creodias.eu`): **sí, HTTP 200 sin
  cabecera de autorización**. Se descarga a `viewer/data/quicklooks/`.

Con cuenta CDSE (gratuita, registro con correo):

- asset `Product` (SAFE completo, ~1,2 GB) por `download.dataspace.copernicus.eu`;
- assets `vv`/`vh` por S3 (`s3://eodata/...`).

El flujo OAuth2 está implementado en `custody/sentinel.py` (`get_token`, `download_product`) y
**no está verificado en ejecución**: no hay cuenta. Para activarlo, rellena
`cdse_credentials.json` o exporta `CDSE_USERNAME` / `CDSE_PASSWORD` y vuelve a lanzar `build.py`.
Sin credenciales el build **no falla**: la capa queda con catálogo y quicklooks, y el manifest
registra el motivo exacto.

**El quicklook está en geometría imagen (range/azimuth), no es un raster norte-arriba.** Se
publica como miniatura en el popup y el footprint como vector exacto. **No se georreferencia al
bbox ni se presenta como medido**: `quicklook_georeferenced` es `false` en el GeoJSON y el visor lo
rotula. Por el mismo motivo `sar_detections` es `null`, no cero: no se han calculado porque exige
el GRD.

---

## Degradación controlada (verificado, no supuesto)

En la prueba de caché fría del 2026-11-09 (`mv cache cache_keep && python3 build.py`) **Overpass
devolvió `HTTP 502 Bad Gateway`** para la consulta de corredores mientras la de puertos pasaba.
Resultado observado: el build **no abortó**, `corridors` y `corridors_other` quedaron declaradas
`sin datos` con el motivo literal `Overpass falló: HTTP Error 502: Bad Gateway`, e **IND-01 e
IND-05 dieron 0 porque dependen del índice de corredores** — no 0 por error, 0 por falta de
entrada. `selftest.py` siguió pasando las 51 comprobaciones estructurales y falló las 4 de
contenido («corredor presente: Estlink 1», etc.), que es exactamente lo que debe hacer.

Consecuencia aplicada: `custody/corridors.py` sube a 5 reintentos y 300 s de timeout para
Overpass (`OVERPASS_RETRIES`, `OVERPASS_TIMEOUT`), lo que da ~2 min de ventana de recuperación,
el tiempo típico de su cola de slots. Y la lección operativa: **en el evento no se consulta
Overpass; el GeoJSON viaja en `cache/`.**

---

## La capa jurídica, y el vacío que enseña

`custody/vayla.py` trae las áreas de restricción a la navegación de Väylävirasto. El tipo
`Ankkurin käyttökielto` (prohibición de fondeo) es la versión **publicada y citable** de «aquí
este buque no debía haber fondeado», con su `diaarinumero` y su fecha de entrada en vigor. Cada
alerta lleva `evidence.anchoring_prohibited_area`.

Medido por el propio pipeline (2026-11-09, AOI 22–30,5 E / 59–60,9 N):

| | |
|---|---|
| Áreas de restricción en el AOI | **521** |
| De ellas, prohibición de fondeo | **6** |
| Prohibiciones de fondeo a ≤ 2 km de un corredor trunk | **0** |

Cinco de las seis están en el canal de Saimaa (vía interior); la sexta queda a 4,3 km de un cable
de telecom en la aproximación del mar de Åland. **Ninguna sobre Estlink 1, Estlink 2, C-Lion 1 ni
Balticconnector en el golfo abierto.** Confirma de forma independiente lo que midió el COO
(`04_coo.md` A.4.1). No es un fallo de la capa: es el vacío jurídico sobre el que hay que
construir el argumento de producto.

---

## Honestidad de las capas

`viewer/data/manifest.json` declara, capa a capa, `status` (`ok` / `vacía` / `sin datos`) y el
motivo. **Sources ▸ Build health** lo muestra tal cual, con lo que falta arriba y sin plegar. Si
una fuente cae, la capa va vacía y etiquetada; **nunca se rellena con datos sintéticos**.

La pestaña Estado se eliminó: enseñaba un `ok` verde sin decir qué significaba. Salud de capas y
licencias están ahora en **Sources**, y los umbrales en **Filters**, junto a los controles que
actúan sobre ellos. `#status` sigue resolviendo a `#sources`.

---

## Límites conocidos

- **La ventana de AIS es la que haya grabado el recorder**, no un archivo histórico. Sin histórico
  no hay calibración de umbrales ni caso Eagle S reproducible.
- **Cobertura AIS = receptores VHF costeros finlandeses.** Un buque fuera de alcance no aparece y
  su ausencia no se distingue de un AIS apagado. Eso limita IND-04 de forma estructural, no
  por implementación.
- **AIS es autodeclarado.** `navStat`, `shipType`, nombre e IMO son lo que el buque dice. Los
  tipos de servicio (práctico, remolcador, SAR) se **marcan**, no se filtran: el tipo es
  falsificable.
- **El polling REST capta ~18 % de los mensajes** (medido en D1: REST 328–408 fixes/min frente a
  MQTT 2.131 msg/min). Para maniobras cortas hace falta `--include-mqtt` con `paho-mqtt`.
- **Profundidad por vecino más próximo** sobre rejilla de 0,01° (~1,1 km), promediada en subrejilla
  3×3 del raster de 116 m. Para una alerta concreta, `depth_sample` da el valor con procedencia.
- **Proyección equirectangular local** para distancias: error < 0,4 % en el AOI. Suficiente para
  umbrales en NM, insuficiente para peritaje métrico.

---

## Atribución para cualquier material derivado

> Source: Fintraffic / digitraffic.fi, licence CC 4.0 BY · (c) OpenStreetMap contributors, ODbL
> 1.0 · EMODnet Bathymetry Consortium — EMODnet Digital Bathymetry (DTM) · Contains modified
> Copernicus Sentinel data · Global Fishing Watch, CC BY-SA 4.0 · US Treasury OFAC SDN (public
> domain) · Wikidata, CC0 · vessel photographs via Wikimedia Commons, per-file licence ·
> EMODnet Human Activities (wrecks, military areas, munitions)

**Ojo con el ShareAlike de GFW.** Es la única fuente del build con una obligación más fuerte que
la atribución. Antes de que esto sea producto hay que mirar si contamina el derivado, y la
respuesta condiciona si la capa se queda. Pendiente de revisión legal.
