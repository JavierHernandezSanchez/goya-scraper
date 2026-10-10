# goya-scraper

Recopila información de **todas las películas nominadas y ganadoras de los Premios Goya**, de la primera edición (1987) a la más reciente disponible (2026), desde la web oficial de la
[Academia de Cine](https://www.premiosgoya.com).

Produce un único fichero, `data/movies.json`, donde **cada película aparece una sola vez**
con todas sus nominaciones y premios.

```
data/movies.json
├── 40 ediciones      (1987 – 2026)
├── 1678 películas
├── 4050 nominaciones
└── 1027 premios
```

Proyecto educativo. El objetivo es que el código se pueda leer y entender entero.

---

## Qué hace

Por cada edición de los Goya:

1. Lee la página de nominaciones y extrae todas las categorías, con sus nominados y
   **quién ganó**.
2. Visita la ficha de cada película nominada y extrae país, dirección, guion, reparto,
   sinopsis, duración y título original.
3. Agrega las nominaciones de esa edición a la película correspondiente.
4. Escribe `data/movies.json`.

Todo con `requests` + `BeautifulSoup` sobre HTML. **Sin APIs externas.**

Además, y como paso aparte, convierte el JSON en una **base de datos SQLite** con un modelo
relacional normalizado, para poder consultar los Goya con SQL: ver *Para consultar los
datos*, más abajo.

---

## Instalación

```bash
cd goya-scraper

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

Requiere **Python 3.10+**. Dependencias: `requests`, `beautifulsoup4` y `pytest`.

> **No necesitas ejecutar el scraper para usar los datos.** `data/movies.json` está
> versionado en el repositorio, así que al clonar ya lo tienes. El scraper solo hace
> falta para *actualizar* esos datos cuando la Academia publique una edición nueva.

---

## Uso

### Para consultar los datos

No hace falta nada más: el JSON está en el repositorio. Para la base de datos:

```bash
python -m goya_scraper.import_db      # movies.json -> goya.db
python -m goya_scraper.db_validate    # comprueba una contra el otro
sqlite3 data/goya.db                  # a preguntar
```

### Para actualizar los datos

Solo cuando quieras volver a pedirle los datos a la Academia:

```bash
python -m goya_scraper
```

Sin argumentos, sin opciones, sin CLI. Eso lo hace todo.

| Ejecución                      | Peticiones          | Tiempo       |
| ------------------------------ | ------------------- | ------------ |
| Primera vez, todo el histórico | 1719                | ~35 min      |
| Segunda vez                    | **0**               | ~3 s         |
| Reanudada tras un corte        | solo lo que faltaba | lo que falte |

> **Lee esto antes de lanzarlo:** recorre el sitio entero, genera muchísimas peticiones y
> tarda bastante. No es una forma rápida de "probar el código": para eso están los tests, que no tocan la red. Si lo lanzas, deja que termine en lugar de interrumpirlo.

> **Estado: proyecto terminado.** El comando recorre las 40 ediciones, escribe
> `data/movies.json` y valida el resultado.

### Salida

```
[INFO] edition 36: 28 categories, 114 nominations, 51 movies, 28 winners
[INFO] done: 51 movies, 114 nominations, 28 awards, 0 failed

El buen patrón  (el-buen-patron)
  nominaciones=20 (la web dice 20)  premios=6 (la web dice 6)
  categorías distintas=17  ediciones=[36]
  país=['España'] (bruto: 'Española')
  dirección=['Fernando León de Aranoa']
  duración=115  campos ausentes=['title_original']
    [GANA] Mejor película — El buen patrón
    [GANA] Mejor dirección — Fernando León de Aranoa
    [    ] Mejor actor de reparto — Celso Bugallo
    ...

contraprueba con los contadores de la web: 51/51 coinciden
```

Esa última línea es la que importa: cada ficha declara cuántas nominaciones y cuántos
premios tiene, y la comparamos con lo que hemos construido nosotros. **51 de 51
coinciden.** Es una validación gratuita: no cuesta una sola petición extra (ADR-012).

### El JSON

Así queda `data/movies.json` (extracto):

```json
{
  "slug": "el-buen-patron",
  "url": "https://www.premiosgoya.com/pelicula/el-buen-patron",
  "title": "El buen patrón",
  "title_original": null,
  "synopsis": "Básculas Blanco, una empresa de producción de balanzas industriales...",
  "countries": ["España"],
  "countries_raw": "Española",
  "duration_minutes": 115,
  "credits": {
    "directors": ["Fernando León de Aranoa"],
    "screenwriters": ["Fernando León de Aranoa"],
    "cast": ["Javier Bardem", "Manolo Solo"],
    "producers_raw": "Reposado Producciones Cinematográficas, Básculas Blanco, A.I.E, Mediaproducción, S.L.U."
  },
  "goya": {
    "editions": [36],
    "total_nominations": 20,
    "total_awards": 6,
    "nominations": [
      {
        "edition": 36,
        "ceremony_year": 2022,
        "category": "Mejor actor de reparto",
        "credited": ["Celso Bugallo"],
        "won": false,
        "note": "Por El buen patrón"
      }
    ]
  },
  "data_quality": {
    "detail_status": "ok",
    "reported_by_source": { "nominations": 20, "awards": 6 },
    "missing_fields": ["title_original"],
    "issues": []
  }
}
```

---

## Estructura

```
goya-scraper/
├── src/goya_scraper/
│   │  ── la descarga ──────────────────────────────
│   ├── __main__.py      # python -m goya_scraper
│   ├── run.py           # el recorrido completo
│   ├── http_client.py   # HTTP, rate limit y User-Agent
│   ├── parse_edition.py # HTML de edición  -> nominaciones
│   ├── parse_movie.py   # HTML de película -> datos de película
│   ├── model.py         # dataclasses + normalización + totales
│   ├── storage.py       # lee y escribe data/movies.json
│   ├── validate.py      # comprueba el resultado y reporta
│   │
│   │  ── dato curado sobre la fuente ──────────────
│   ├── categories.py    # 33 etiquetas -> 31 categorías
│   ├── credited_kinds.py # qué contiene 'credited' en cada categoría
│   ├── persons.py       # 90 fusiones de nombres
│   │
│   │  ── la base de datos ─────────────────────────
│   ├── db.py            # conexión y creación
│   ├── schema.sql       # 13 tablas, 10 índices, 1 vista
│   ├── import_db.py     # movies.json -> goya.db
│   └── db_validate.py   # comprueba la base contra el JSON
├── tests/               # 394 tests, sin internet
├── data/movies.json    # el resultado. Fuente de verdad, versionado en el repo
├── data/goya.db        # la copia consultable (se regenera, no se versiona)
├── cache/              # HTML crudo (no se versiona)
├── LICENSE             # MIT
├── AGENTS.md           # reglas de trabajo e invariantes del proyecto
└── docs/
```

Las dos funciones de parseo **no hacen peticiones**: reciben HTML y devuelven datos. Por
eso los tests no necesitan internet ni mocks.

La tercera línea son los módulos de base de datos, y **no se importan entre sí con la
primera**: `run.py` no sabe que existe SQLite. Lo comprueba el test
`test_the_scraper_does_not_import_the_database`.

---

## Dónde están los datos

```
data/movies.json    # la fuente de verdad. El scraper lo escribe, nada más. Versionado.
data/goya.db        # una proyección consultable. Se reconstruye desde el JSON
```

`data/movies.json` está versionado en el repositorio, así que se puede consultar sin
ejecutar nada. Si prefieres SQL, un comando lo convierte en base de datos.

|                                     | Documentación                              |
| ----------------------------------- | ------------------------------------------ |
| `movies.json`, campo a campo        | [`docs/data-model.md`](docs/data-model.md) |
| El modelo relacional, tabla a tabla | [`docs/database.md`](docs/database.md)     |

**Licencia:** MIT, en [`LICENSE`](LICENSE). Los datos vienen de la Academia de Cine; mira
la [nota sobre los datos](#nota-sobre-los-datos) antes de redistribuirlos.

---

## Tests

```bash
pytest
```

**Los tests no usan internet.** Todo el HTML de ejemplo son ficheros reales guardados en
`tests/fixtures/`.

Cubren: parseo de HTML, extracción de nominaciones, detección de ganadores, normalización de datos, deduplicación, lectura y escritura del JSON, comportamiento incremental, y todo el camino hasta la base de datos: el esquema, las restricciones, la importación, la reproducibilidad y la validación.

Sobre la base de datos hay una clase de test que merece mención aparte: los que
**insertan datos malos y exigen que la base los rechace**. Comprobar que existen trece
tablas no dice nada; comprobar que una duración de `'105 años'` falla sí.

---

## Documentación

| Documento                                      | Contenido                                                        |
| ---------------------------------------------- | ---------------------------------------------------------------- |
| [`docs/architecture.md`](docs/architecture.md) | Módulos, responsabilidades, flujo y decisiones de diseño         |
| [`docs/data-model.md`](docs/data-model.md)     | Cada campo de `movies.json`, campo por campo                     |
| [`docs/sources.md`](docs/sources.md)           | Fuentes, qué aporta cada una, y por qué se descartaron las demás |
| [`docs/scraping.md`](docs/scraping.md)         | Recorrido, rate limiting, caché, errores, incrementalidad        |
| [`docs/development.md`](docs/development.md)   | Entorno, ejecución, tests, cómo añadir cosas                     |
| [`docs/validation.md`](docs/validation.md)     | Qué se comprueba y qué se ha encontrado                          |
| [`docs/database.md`](docs/database.md)         | El modelo relacional, el esquema, los índices y las consultas    |
| [`docs/decisions.md`](docs/decisions.md)       | Registro de decisiones (38 ADR)                                  |
| [`AGENTS.md`](AGENTS.md)                       | Cómo trabajar en el proyecto: invariantes, tests y proceso       |

---

## Principios

Este proyecto se hizo con algunas reglas que no se negocian:

- **No se inventan datos.** Si un campo no está en la fuente, es `null`. No se derivan
  datos ni se rellenan huecos con suposiciones.
- **Los datos contradicciones se registran, no se resuelven en silencio.**
- **Cada película es un registro.** La identidad la da el servidor (el `slug` de la URL),
  así que no hace falta matching difuso.
- **Educado con el servidor:** 1.2 s entre peticiones, `timeout` siempre, reintentos
  limitados, `robots.txt` comprobado, nada de concurrencia agresiva.
- **No se saltan protecciones.** Ni CAPTCHAs, ni Cloudflare, ni 403 ni 429. Si un sitio
  bloquea, se para.
- **Errores individuales no paran el proceso.** Una película que falle no tira el resto.
- **100 líneas claras** antes que 500 líneas de abstracción.

---

## Lo que no está

Decisiones tomadas de forma consciente, todas ellas en
[`docs/decisions.md`](docs/decisions.md):

- **Sin año de película.** La fuente no lo tiene y no se deriva.
- **Sin género, presupuesto ni recaudación.** No aparecen en el sitio.
- **Sin IMDb, Rotten Tomatoes ni Filmaffinity.** IMDb está **prohibida por su
  `robots.txt`**; Filmaffinity está tras Cloudflare; Rotten Tomatoes exigiría un sistema
  de matching desproporcionado para el beneficio.
- **Sin base de datos dentro del scraper.** La hay, pero fuera: `import_db` cuelga de `storage` y el recorrido de descarga no la importa.
- **Sin ORM.** `sqlite3` de la librería estándar y SQL a mano. Un ORM escondería
  precisamente lo que esta fase enseña: las claves foráneas, los `JOIN` y los índices.
- **Sin CLI.** Se ejecuta con `python -m goya_scraper`. Las dos órdenes de la base de datos
  aceptan rutas opcionales y nada más.
- **Sin tabla de géneros ni de productoras.** Lo primero no existe en la fuente; lo segundo
  es un string que no se puede partir sin inventar.
- **Dos categorías históricas sin unificar a propósito.** «Mejor guion» (ed. 1-2) y
  «Mejor cortometraje» (ed. 4-6, 12, 15) se conservan tal cual: la web nunca dice si la
  primera era original o adaptada, ni si la segunda era de ficción, animación o documental.
  Repartirlas sería inventar. ADR-022.

---

## Nota sobre los datos

Los datos de las fichas los aportan las productoras de las películas, según el pie de la web
de la Academia. Este proyecto es un ejercicio de aprendizaje y no está afiliado a la Academia de Cine.

---

## Estado

**Scraper y base de datos terminados.** Lo verificado:

**Dataset completo:** 40 ediciones (1987–2026) · 1678 películas · 4050 nominaciones ·
1027 premios · 31 categorías canónicas.

**Validación del JSON: 0 errores, 12 avisos, 2 informativos.** Los 12 avisos son 6 películas
donde la web se contradice consigo misma. Ninguna es un error del scraper: las 4050
nominaciones coinciden **1678/1678** con los contadores de la Academia. Ver
[`docs/validation.md`](docs/validation.md).

**Base de datos: 0 errores.** 6033 personas (de 6130 grafías), 4050 nominaciones, 5277
créditos. La validación cruzada entre `movies.json` y `goya.db` da
**0 errores, 2 avisos, 4 informativos**, y `PRAGMA integrity_check` da `ok`. Ver
[`docs/database.md`](docs/database.md).

| Qué                         | Resultado                                                                 |
| --------------------------- | ------------------------------------------------------------------------- |
| Descubrimiento de ediciones | Las 40, con su año leído del HTML                                         |
| Incrementalidad             | Segunda ejecución con **0 peticiones**                                    |
| Recuperación ante corte     | Reanuda por edición, sin perder lo anterior                               |
| Reintentos                  | 5xx y error de red: 3 intentos, esperas 2/4/8 s                           |
| Sin reintentos              | 404, 403, 429: un solo intento                                            |
| `robots.txt`                | Se lee y se aplica; 404 = sin restricciones                               |
| Escritura atómica           | Un fallo a mitad conserva el fichero bueno                                |
| JSON corrupto               | Lanza excepción y **no** sobrescribe                                      |
| Cada película una sola vez  | 1678 objetos, 1678 `slug` distintos, 0 duplicados                         |
| Validación                  | 0 errores, empates informativos, conflictos nombrados por categoría       |
| Catálogo de categorías      | 33 etiquetas del sitio → 31 canónicas, con la original siempre a mano     |
| `credited` polimórfico      | 20 categorías de persona, 10 de obra, 1 de canción, **0 inconsistencias** |
| Fusiones de nombres         | 6130 grafías → 6033 personas, 90 grupos curados a mano                    |
| Esquema SQLite              | 13 tablas `STRICT`, 10 índices, 1 vista; `integrity_check` = `ok`         |
| Importación reproducible    | Dos importaciones del mismo JSON → la misma base de datos                 |
| Importación atómica         | Un fallo deshace todas las filas de esa ejecución                         |
| JSON ↔ SQLite               | 0 errores, 2 avisos, 4 informativos                                       |
| Tests                       | **394**, ninguno toca la red                                              |

### Los 12 avisos, en una frase

Seis películas tienen el recuento de premios distinto entre la página de edición y su ficha.
El programa **nombra qué premio concreto** discrepa en cada caso, en vez de elegir en
silencio una de las dos fuentes.

Detalle completo en [`docs/validation.md`](docs/validation.md).

### Una consulta para ver la diferencia entre los dos modelos

El JSON es un documento centrado en la película: la nominación está *dentro* de ella. Para
saber quién ganó algo hay que recorrer 1678 objetos. En la base de datos son 4050 filas:

```bash
sqlite3 data/goya.db "SELECT p.name, COUNT(*) FROM nomination n
  JOIN nomination_credit nc ON nc.nomination_id = n.id
  JOIN person p ON p.id = nc.person_id
  JOIN category c ON c.id = n.category_id
  WHERE n.won = 1 AND c.name LIKE 'Mejor direcci%'
  GROUP BY p.id ORDER BY 2 DESC LIMIT 5;"
```

```
Javier Aguirresarobe|6
José Luis Alcaine|5
Félix Murcia|5
José Luis Escolar|4
J.A. Bayona|4
```

Con `LIKE 'Mejor direcci%'` entran las tres categorías de dirección, así que el primer
puesto es un **director de fotografía**, no un director. Para directors de verdad hay que
nombrar las dos categorías exactas, y entonces sale `J.A. Bayona` con 4.

Que `J.A. Bayona` aparezca con dos grafías distintas en el JSON y salga **una sola vez** en
las dos consultas es el detalle que justifica la tabla de fusiones.