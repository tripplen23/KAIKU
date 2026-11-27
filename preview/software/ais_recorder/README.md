# ais_recorder — grabador AIS del Báltico

> **Cómo se opera está en [../MANUAL.md §0](../MANUAL.md), y solo ahí.** Este
> fichero cubre **arquitectura**: formato, requisitos, contrato con el motor de
> custodia. Si un dato aparece en los dos, manda el MANUAL. Qué cambió y por
> qué: [../CHANGELOG.md](../CHANGELOG.md), que es único para el grabador y el
> visor porque son un sistema.

Graba de forma continua el tráfico AIS que publica **Fintraffic Digitraffic Marine**.
Entregable D1 (`investigacion_preliminar/13_decisiones_ceo.md`).

Fuente de datos: **Fintraffic / digitraffic.fi, licencia CC 4.0 BY**.
Esa cadena literal debe aparecer en cualquier material derivado (pitch del hackatón incluido).
<https://www.digitraffic.fi/en/terms-of-service/>

- **Dependencias: ninguna** para el camino principal (`recorder.py` + `aisctl.py`, Python ≥3.9, solo stdlib).
- `mqtt_ingest.py` es **opcional** y requiere `paho-mqtt`.

---

## Arranque, parada y systemd

En [../MANUAL.md §0](../MANUAL.md). Lo único que conviene repetir aquí, porque es
arquitectura y no uso:

**La raíz del almacén la decide `custody_mvp/config/custody.toml`**, el mismo
fichero que lee la aplicación. El grabador no tiene una idea propia de dónde
viven los datos — tenerla fue lo que costó 4,6 h de grabación invisible el
2026-11-13. Orden de precedencia: `--root` → `AIS_DATA_ROOT` → el TOML → su
propio `data/`. Arrancar contra una raíz que no es la configurada **avisa en el
log** con el comando para fusionarlo después; no se bloquea, porque puede ser
deliberado.

Un reinicio no duplica ni pierde: el índice de deduplicación se reconstruye del
fichero del día y la escritura sigue en modo *append*.

### Stream de alta fidelidad (opcional)

```bash
pip install --user paho-mqtt      # o en venv; el sistema es PEP-668
python3 mqtt_ingest.py            # en paralelo con recorder.py, no en su lugar
```

---

## Dónde quedan los datos, y por qué ahí

La estructura de ficheros y la tabla de streams, en
[../MANUAL.md §0](../MANUAL.md). Lo que es decisión de arquitectura:

**El almacén está DENTRO de Dropbox a propósito, y es lo único que lo está.**
Versiones anteriores de este fichero recomendaban lo contrario — sacarlo de
Dropbox por el tráfico de sincronización de ~19 MiB/día. Ese consejo estaba
invertido y se ha borrado: la grabación es **lo único del sistema que no se
puede reconstruir**, y sincronizar lo irreemplazable es exactamente lo que hay
que sincronizar. Lo que no debe sincronizarse son los 1,9 GB de teselas
regenerables, y durante un tiempo fue al revés por accidente. Las tres
categorías y el criterio están en [../MANUAL.md §2b](../MANUAL.md).

**Un escritor por raíz**, garantizado con `flock` sobre `recorder.lock`
(REQ-AIS-011). Dos grabadoras sobre el mismo almacén no se pisarían los
registros gracias al formato, pero sí duplicarían peticiones a Digitraffic.

---

## Cómo consultarlo

Los comandos de `aisctl.py`, en [../MANUAL.md §0](../MANUAL.md). `aisctl` **nunca
escribe en `raw/`**; la única herramienta que lo hace es `merge_store.py`, y su
razón de ser está en [../MANUAL.md §2b](../MANUAL.md).

### Interfaz con C3 (motor de custodia, `canal/iteracion_01/04_coo.md` A.2)

`aisctl sqlite` materializa el contrato, regenerable en cualquier momento:

```sql
locations(mmsi, t_utc, ts_ms, lat, lon, sog, cog, heading, nav_stat, rot, pos_acc)
          PRIMARY KEY (mmsi, ts_ms)         -- idempotente, re-ejecutable
vessels  (mmsi, name, ship_type, imo, call_sign, destination, draught, t_ms)
polls    (seq, rx_ms, http, received, new, error)
```

Las reglas R-A a R-D de C3 son computables con estos campos. **Dos trampas de interfaz que
romperían R-B en silencio:**

1. *Un buque nunca "desaparece" del feed.* El endpoint sigue sirviendo su último fix durante
   ~24 h. "Perdió AIS" se detecta porque `ts_ms` **deja de avanzar**, no porque el MMSI deje de
   aparecer. Quien escriba R-B contra "ausencia de fila" obtendrá cero alertas.
2. *Un hueco en los datos no es un hueco en el AIS.* Si el grabador estuvo caído, todos los
   buques parecen haber callado a la vez. Por eso la tabla `polls` existe y `aisctl gaps` mide
   la continuidad **sobre el log de polls**, no sobre los datos. R-B debe excluir las ventanas
   que `gaps` declare.

`rot = -128` significa "no disponible" y `sog = 102.3` significa "no disponible" en AIS; no son
valores físicos. El grabador los persiste tal cual (REQ-AIS-005); filtrarlos es trabajo de C3.

Sin herramientas: `zcat data/raw/locations/2026/10/*.gz | jq -c 'select(.sog < 1)'`.

Rollup opcional a Parquet (requiere pyarrow, offline, el NDJSON sigue siendo la fuente de verdad):

```python
import store, pyarrow as pa, pyarrow.parquet as pq
r = list(store.iter_records('data/raw/locations/2026/10/locations-2026-10-28.ndjson.gz'))
pq.write_table(pa.table({k: [x.get(k) for x in r] for k in r[0]}),
               'locations-2026-10-28.parquet', compression='zstd')
```

---

## Requisitos

Verificables, numerados. El método de verificación está en la última columna; la evidencia de
ejecución está en `canal/iteracion_01/01_systems_engineer.md` §4.

| # | Requisito | Verificación |
|---|---|---|
| REQ-AIS-001 | Captura todo `/api/ais/v1/locations` sin filtro geográfico ni de tipo de buque. El filtrado es un problema de consulta, no de grabación | Inspección de `location_records()`; `summary.unique_mmsi` = features recibidas |
| REQ-AIS-002 | Cadencia nominal 60 s de pared, sin acumular deriva. No se baja de 60 s: el TTL de caché upstream es `max-age=60` | `polllog`: Δ`rx_ms` entre ciclos |
| REQ-AIS-003 | Toda petición lleva `Digitraffic-User` y `Accept-Encoding: gzip` (obligatorio en los ToS), y `If-None-Match` cuando hay ETag | `curl -v`; constante `DIGITRAFFIC_USER` |
| REQ-AIS-004 | Carga ≤1 req/min en `/locations` y ≤1/10 min en `/vessels`. Límite sin cabecera: 60 req/min por IP | Conteo en `polllog` |
| REQ-AIS-005 | Los campos de la API se persisten literales. Ningún renombrado, conversión o campo derivado en el stream crudo | Diff campo a campo contra la respuesta de la API |
| REQ-AIS-006 | Un fix de posición se escribe como máximo una vez. Clave `(mmsi, timestampExternal)` | Conteo de claves duplicadas sobre el fichero del día |
| REQ-AIS-007 | Un fallo de red nunca termina el proceso. Se registra en `polllog` con el error y se reintenta con backoff exponencial con jitter, tope 300 s | Ensayo con host irresoluble |
| REQ-AIS-008 | Reanudación sin pérdida ni duplicado: el índice de dedup se reconstruye leyendo el fichero del día. El fichero es el único estado | Parar, arrancar, contar duplicados |
| REQ-AIS-009 | Un `SIGKILL` no corrompe el almacén. Pérdida máxima = un ciclo (REST) o un flush de 30 s (MQTT) | `kill -9` en marcha + `aisctl verify` |
| REQ-AIS-010 | La corrupción es detectable sin metadatos externos: cada miembro gzip lleva su CRC32 | Truncado deliberado + `aisctl verify` |
| REQ-AIS-011 | Un único escritor por almacén, garantizado por `flock` | Lanzar dos instancias |
| REQ-AIS-012 | Presupuesto de disco ≤1 GiB/30 días para el stream REST | `aisctl stats` sobre ventana medida |
| REQ-AIS-013 | La pérdida de fidelidad del polling frente al stream de difusión está cuantificada, no supuesta | Captura simultánea REST vs MQTT |
| REQ-AIS-014 | El ingestor MQTT detecta una conexión medio abierta y fuerza reconexión si no llega ningún mensaje en 180 s | Inspección del watchdog; contador `reconnects` |

### Lo que estos requisitos NO cubren

- **No hay AIS histórico.** La API es en vivo. El primer poll de cada sesión recupera la
  ventana de ~24 h que mantiene el upstream, y nada más. Diciembre de 2024 no es recuperable
  por esta vía (ver el anexo del canal, riesgo R1).
- **No hay autenticación de los datos.** AIS es autodeclarado. El grabador registra lo que el
  buque dice, no lo que hace.
- **Cobertura:** receptores terrestres finlandeses. Un buque fuera del alcance VHF de la red
  no aparece, y su ausencia no se distingue de un AIS apagado.

---

## Decisión de formato: NDJSON.gz, no Parquet

Medido sobre los mismos 7.360 registros reales (2026-10-27):

| Formato | B/registro | Relativo |
|---|---|---|
| NDJSON sin comprimir | 249,0 | 7,8× |
| **NDJSON.gz (lo que se usa)** | **32,02** | **1,00×** |
| Parquet snappy, un row group | 30,59 | 0,96× |
| Parquet zstd, un row group | 26,27 | 0,82× |
| Parquet zstd, un row group por ciclo de 60 s | 41,50 | **1,30×** |

La última fila es la que decide. Parquet solo gana el 18 % si se escribe el día entero de una
vez; escrito en streaming —un row group por ciclo, que es lo que exige no perder datos— es un
30 % **peor** que gzip, porque cada row group paga su propia cabecera y pierde el contexto de
compresión. La alternativa, bufferizar el día en RAM y escribir a medianoche, pone hasta 24 h de
datos en riesgo ante un corte: contradice el requisito principal.

Añádase que `pyarrow` son 54 MB de rueda y un venv en este sistema (PEP 668). Parquet se queda
donde sirve: como derivado offline regenerable desde el NDJSON, nunca como fuente de verdad.

Por qué gzip multimiembro y no un único stream gzip: RFC 1952 permite concatenar miembros, y
`gzip`/`zcat`/`gzip.open` los leen de forma transparente. Eso da append barato, `fsync` por
ciclo, y CRC32 por bloque. Un único stream gzip habría que cerrarlo para que fuera legible.
