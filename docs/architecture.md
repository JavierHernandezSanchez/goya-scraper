# Arquitectura

## Idea central

El proyecto hace **un solo recorrido**: por cada edición, leer sus nominaciones; por cada
película citada, leer su ficha; ensamblar el resultado y escribir un JSON.

No hay orquestador, ni CLI, ni inyección de dependencias, ni registro de plugins. Todo el
control está en un módulo (`run.py`) y se lee de arriba abajo.

---

## Módulos

```
src/goya_scraper/
├── __main__.py      # python -m goya_scraper
├── run.py           # el recorrido completo, de arriba abajo (y el logging)
├── http_client.py   # HTTP: caché en disco, reintentos, rate limit, robots.txt
├── parse_edition.py # HTML de edición   -> nominaciones    (función pura)
├── parse_movie.py   # HTML de película  -> datos de película (función pura)
├── model.py         # dataclasses, normalización y totales
├── storage.py       # lectura y escritura de data/movies.json
├── categories.py    # catálogo curado de categorías (ADR-022)
├── validate.py      # comprobación del resultado y informe
├── credited_kinds.py # qué contiene 'credited' en cada categoría (ADR-030)
├── persons.py       # fusiones de nombres curadas (ADR-027)
├── db.py            # conexión y creación de la base de datos
├── schema.sql       # las 13 tablas, 10 índices y la vista
├── import_db.py     # movies.json -> goya.db
└── db_validate.py   # comprobación de la base contra el JSON
```

Catorce módulos, en dos mitades que no se mezclan. Ni una clase que envuelva a otra, ni un
patrón, ni una interfaz. Para un proyecto de este tamaño, cada capa que se añade se paga en
legibilidad.

La línea que las separa es una sola: **el scraper no sabe que existe la base de datos**.
`http_client`, `parse_*`, `run`, `model` y `storage` no importan `sqlite3`. La otra mitad
(`db`, `import_db`, `db_validate`) cuelga de `storage`, nunca al revés. Hay un test que lo
comprueba importando `run` en un subproceso y verificando que `goya_scraper.db` no está en
`sys.modules` (ADR-036).

Y `credited_kinds.py` y `persons.py` no importan nada, igual que `categories.py`: son
conocimiento curado sobre la fuente, no sobre el almacenamiento. Por eso son reutilizables
por el scraper si alguna vez hace falta arreglar el dato en origen.

La configuración de logging son seis líneas dentro de `run.py`. No merece un módulo
propio, y un archivo de diez líneas que solo envuelve `basicConfig` es exactamente el
tipo de abstracción que este proyecto evita.

### `http_client.py`

**Responsabilidad:** dada una URL, devolver HTML. Es el **único** módulo que sabe que
existe internet.

Es el módulo más grande del proyecto (unas 199 líneas) y concentrate todo lo que habla
con la red. Esa es la razón de que esté en un solo sitio.

- **Caché en disco.** Antes de pedir, mira si existe el fichero. Si existe, lo devuelve.
  Es lo que hace la incrementalidad (ADR-010) y lo que permite testear sin red.
  Un acierto de caché **no** espera entre peticiones (ADR-017).
- **Reintentos** con espera creciente (2 s, 4 s, 8 s) ante error de red o HTTP 5xx.
- **Rate limit** con una pausa mínima entre peticiones que sí salen.
- **`User-Agent` identificable**, con un enlace de contacto.
- **`timeout`** siempre. Nunca una petición sin límite de tiempo.
- **Respeta `robots.txt`** con `urllib.robotparser`, leído una sola vez por cliente.

Lo que **no** hace: reintentar un 404, reintentar un 403 ni un 429, ni intentar sortear
nada. Un 403 o un 429 se registra y la ejecución continúa con la siguiente película.

Se le puede pasar una `session` distinta en el constructor. Los tests lo hacen con un
doble propio, así que **ningún test toca la red**.

### `parse_edition.py` y `parse_movie.py`

**Responsabilidad:** HTML en, estructuras Python fuera. **No hacen peticiones.**

Son funciones puras a propósito, y esta es la decisión que más nos paga:

```python
def parse_edition(html: str, edition: int, ceremony_year: int) -> list[Nomination]
def parse_movie(html: str, slug: str) -> Movie
```

Si el scraper no está dentro, entonces:

- los tests de parsing son tests normales que leen un fichero de `tests/fixtures/`;
- **no hace falta `mock`, ni `responses`, ni `monkeypatch`**;
- fallar un test significa que el HTML cambió, no que la red falló.

### `model.py`

**Responsabilidad:** las estructuras de datos y las reglas de transformación.

- `Nomination` y `Movie` como `dataclasses`.
- `normalise_persons()`, `normalise_countries()`, `parse_duration()`: las funciones de
  limpieza, que son puras y están testeadas de forma aislada.
- `dedupe_by_slug()`: la deduplicación. Un `dict` por `slug`, tan simple como suena.

Sin más clases. Si alguna vez hiciera falta más, se añadiría entonces.

### `storage.py`

**Responsabilidad:** `movies.json`.

- `load()` -> el documento, o uno vacío si el fichero no existe. **Lanza excepción si el
  JSON está corrupto** (ADR-015), porque empezar de cero destruiría el fichero.
- `build_document(movies, editions)` arma el envoltorio con `_meta`.
- `save(document)` escribe con `indent=2` y `ensure_ascii=False`, y **recalcula `counts`**
  antes de escribir. Nunca se guarda un contador a mano.
- **Escritura atómica:** se escribe a `movies.json.tmp` y se renombra. Si el proceso muere a
  mitad, el fichero bueno sigue intacto. Hay un test que lo comprueba simulando la muerte.

Ordena las películas por título sin acentos ni mayúsculas (ADR-013). No usa `locale`, porque
eso daría un orden distinto en cada máquina y `git diff` dejaría de servir.

### `validate.py`

**Responsabilidad:** comprobar que el documento que acabamos de escribir tiene sentido.

- `validate(document) -> list[Finding]`: función **pura** sobre el diccionario. No toca la
  red, no lee ficheros. Por eso sus 27 tests corren en milisegundos.
- `render(document, findings) -> str`: el informe para leer.

Clasifica en tres niveles (ERROR / AVISO / INFO) porque no todo lo raro es un bug: los
empates son reales, y las discrepancias con la web son de la fuente. Ver
`docs/validation.md` y ADR-019.

**Nunca detiene el proceso.** Los datos valen aunque tengan errores; lo que hace falta es
señalar los errores, no impedir que se guarden.

### `run.py`

**Responsabilidad:** el recorrido. Es el único módulo con lógica de negocio, y se lee
como una lista de pasos:

```
1. logging
2. cargar data/movies.json si existe
3. por cada edición pendiente:
     a. bajar la página de nominaciones
     b. parsear y agrupar por slug
     c. por cada slug: bajar y parsear la ficha
     d. fusionar en el diccionario por slug    <-- aquí está la deduplicación
4. ensamblar el documento y escribirlo
5. resumen por log, con la contraprueba
6. validar el documento y imprimir el informe
```

Tres funciones con nombre de verbo, que se leen de arriba abajo:

- `fetch_movie(client, slug, nominations)` — una película, incluyendo qué pasó si falló.
- `add_movie(movies, movie)` — **la deduplicación**: un `dict.get`, y si la película ya
  existe se le **añaden** las nominaciones nuevas sin perder la ficha ya descargada.
- `scrape_edition(client, edition, year, movies)` — una edición entera.

Un error en el paso 3c afecta a una sola película: se registra y se sigue con la
siguiente. El proceso no se detiene.

---

## Flujo general

```
premiosgoya.com
     │
     ├── GET /                        → lista de ediciones        (1 petición)
     │
     └── GET /{n}-edicion/nominaciones/
              │
              └── 40 páginas → 4050 nominaciones
                       │
                       └── agrupar por slug → 1678 películas únicas
                              │
                              └── GET /pelicula/{slug}/   →  1678 fichas
                                       │
                                       └── Movie  (add_movie: deduplicar)
                                              │
                                              ▼
                                    storage.build_document()
                                              │
                                              ▼
                                    data/movies.json
                                              │
                              python -m goya_scraper.import_db
                                              │
                                              ▼
                                        data/goya.db
                                              │
                              python -m goya_scraper.db_validate
```

**Total: 1719 peticiones** para el histórico completo. Después de eso, **0**.

La segunda mitad del diagrama es opcional y va separada: el scraper funciona entero sin
ella. `movies.json` es la fuente de verdad y `goya.db` es una copia consultable que se
reconstruye desde el JSON cuando se quiera.

| Orden | Qué hace | Cuándo |
|---|---|---|
| `python -m goya_scraper` | Descarga y escribe `movies.json` | Cuando cambian los datos |
| `python -m goya_scraper.import_db` | Escribe `goya.db` | Después de importar |
| `python -m goya_scraper.db_validate` | Comprueba una contra el otro | Después de importar |
| `sqlite3 data/goya.db` | Consultar | Cuando quieras preguntar algo |

---

## Por qué estas decisiones

**Módulos planos y no subpaquetes.** ADR-005. El proyecto son ~400 líneas; con subpaquetes
los `__init__.py` serían más largos que los módulos.

**Funciones de parseo puras y separadas de `requests`.** Es la razón principal por la que
los tests no necesitan internet. Merece la pena incluso si cuesta un `import` más.

**Sin clase `Scraper` ni clase `MovieRepository`.** Una clase que envuelve una función no
añade nada. Cuando un módulo tiene cinco funciones con nombres claros, el módulo *es* la
abstracción.

**El ensamblado vive en `run.py`, no en `storage.py`.** Son responsabilidades distintas:
`storage.py` sabe de JSON, `run.py` sabe deDatas de Goyas. Mezclarlas es lo que convierte
un proyecto pequeño en ilegible.

**El diccionario por `slug` es el estado del proceso.** No hay base de datos, ni índice
secundario, ni tablas **durante la descarga**. El estado vive en un `dict` en memoria y se
persiste al final. La base de datos SQLite es un paso posterior y aparte, que reconstruye
su contenido desde el JSON.

**La base de datos es una proyección, no una fuente.** El JSON se lee y no se escribe nunca
desde `import_db`. Por eso se puede borrar `goya.db` en cualquier momento sin perder nada.

**El esquema es un `.sql`, no una constante de Python.** Se inspecciona con cualquier
editor y se ejecuta con `sqlite3` sin pasar por Python, que es lo que uno quiere al leer el
modelo por primera vez (ADR-037).

**El dato curado vive fuera de la persistencia.** `categories.py`, `credited_kinds.py` y
`persons.py` son afirmaciones sobre la fuente, no sobre el almacenamiento. Por eso
`persons.py` no importa `sqlite3` aunque su tabla (`person_alias`) sea la que hace
reversibles sus propias fusiones.

---

## Lo que este diseño NO tiene, y por qué

| Ausente | Por qué |
|---|---|
| Cola de trabajo o concurrencia | 1719 peticiones es un trabajo de minutos, no de horas. `requests` síncrono con un rate limit es más simple y más educado que ir en paralelo. |
| Backoff exponencial con *jitter* | Espera creciente fija (2/4/8 s). El jitter existe para que varios clientes no reintenten a la vez; aquí hay uno solo, así que solo añadiría ruido. |
| Validaciones con Pydantic | El JSON se genera y se consume en el mismo proyecto. Validarlo a la escritura es trabajo extra sin destinatario. |
| Un `settings.py` o fichero de config | Cuatro constantes (rate limit, timeout, reintentos, rutas) viven en `http_client.py` y `run.py`. Un fichero de configuración para eso es ceremonia. |
| Sistema de logging estructurado | `logging` de la stdlib con un `basicConfig` cubre el caso. |
| Cache con invalidación por edad o ETag | El servidor no manda `ETag` ni `Last-Modified`, así que no hay contra qué revalidar (ADR-010). |
| ~~Base de datos~~ | Ya existe, pero **fuera** del scraper: `import_db.py` cuelga de `storage` y el scraper no la importa (ADR-036). Sigue sin ser parte del recorrido de descarga, que solo necesita el JSON. |
| CLI con `argparse` | Requisito explícito tuyo. Se ejecuta con `python -m goya_scraper`. |

Cada fila es una decisión, no una carencia. Si alguna vez el proyecto crece y una de ellas
empieza a doler, está anotado *qué* cambiar y *por qué*.