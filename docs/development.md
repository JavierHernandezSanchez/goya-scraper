# Desarrollo

Cómo instalar, ejecutar y probar el proyecto.

---

## Requisitos

- **Python 3.10 o superior** (probado en 3.12).
- Acceso a `https://www.premiosgoya.com`.

Dependencias, y solo dos:

```
requests>=2.31
beautifulsoup4>=4.12
```

más `pytest>=7.4` para desarrollar.

**No hace falta `lxml`.** BeautifulSoup usa el parser de la librería estándar
(`html.parser`) y el HTML del sitio es limpio. Una dependencia menos (ADR-011).

---

## Instalación

### Opción A — Entorno virtual (recomendada)

```bash
cd goya-scraper

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

`pip install -e .` instala el paquete en modo editable desde `src/`, así que los cambios en
el código se aplican sin reinstalar.

### Opción B — Sin entorno virtual

```bash
cd goya-scraper
pip install --user -e ".[dev]"
```

---

## Ejecutar

Un solo comando. No hay argumentos, no hay subcomandos, no hay CLI:

```bash
python -m goya_scraper
```

Eso hace **todo**: descubre las ediciones, descarga lo que falta, y escribe
`data/movies.json`.

| Ejecución | Tiempo | Peticiones |
|---|---|---|
| Primera vez | ~35 min | 1719 |
| Siguientes | segundos | 0 |

Se puede interrumpir con `Ctrl+C` en cualquier momento. Lo descargado queda en `cache/` y
la siguiente ejecución continúa donde se quedó.

### La base de datos, en dos órdenes

```bash
python -m goya_scraper.import_db          # movies.json -> data/goya.db
python -m goya_scraper.db_validate        # comprueba una contra el otro
```

Ambas aceptan dos rutas opcionales y nada más:

```bash
python -m goya_scraper.import_db data/movies.json data/goya.db
python -m goya_scraper.db_validate data/movies.json data/goya.db
```

`import_db` **reconstruye** la base entera: borra el fichero, crea el esquema y lo llena
todo dentro de una transacción. Si algo falla, deshace todas las filas de esa ejecución y
deja una base válida pero vacía; la recuperación es volver a ejecutar el comando. Es
reproducible: importar dos veces el mismo JSON da el mismo archivo, porque los
identificadores los asigna el importador en orden y no SQLite.

Para consultarla:

```bash
sqlite3 data/goya.db
sqlite3 data/goya.db "SELECT title, total_awards FROM movie_totals
                      ORDER BY total_awards DESC LIMIT 10;"
```

Para cambiar el modelo, el punto de partida es `src/goya_scraper/schema.sql`, que es un
fichero de texto normal. Los tests que importan son de comportamiento: insertan datos
malos y exigen que la base los rechace, porque comprobar que existen trece tablas no dice
nada.

---

## Tests

```bash
pytest                      # todos
pytest -v                   # con el nombre de cada test
pytest tests/test_parse_edition.py -v
pytest -k winners           # solo los que mencionan "winners"
```

Los 394 tests se reparten así:

| Fichero | Qué cubre |
|---|---|
| `test_model.py` | `clean_text`, `split_people`, `parse_countries`, `parse_duration` |
| `test_parse_edition.py` | Categorías, nominaciones, ganadores, versiones antiguas |
| `test_parse_movie.py` | Campos, ausencias, 404, entidades HTML |
| `test_storage.py` | Ida y vuelta, escritura atómica, `counts`, JSON corrupto |
| `test_http_client.py` | Caché, reintentos, robots.txt, rate limit, `User-Agent` |
| `test_dedupe.py` | Una película = un registro, fusión entre ediciones, fallos |
| `test_incremental.py` | Descubrimiento de ediciones, `from_dict`, editions ya hechas |
| `test_validate.py` | Estados imposibles, conflictos con la fuente, empates |
| `test_categories.py` | El catálogo curado: fusiones y etiquetas que no se tocan |
| `test_credited_kinds.py` | Los 31 tipos de crédito, comprobados contra los datos reales |
| `test_persons.py` | Las 90 fusiones de nombres, y que un título nunca sea una persona |
| `test_db.py` | El esquema: estructura, y restricciones comprobadas por comportamiento |
| `test_import_db.py` | La importación: recuentos, determinismo, rollback, negarse a adivinar |
| `test_db_validate.py` | Cada comprobación, con el dato roto a propósito |
| `test_integration.py` | Contraprueba contra los contadores de la web |

**Ninguno toca la red.** `test_http_client.py` inyecta un doble de `requests.Session`
propio, así que se prueban la caché, los reintentos y el rate limit sin salir a internet.

Los tests que escriben en disco usan siempre un directorio temporal de `tmp_path`, así que
nunca pisan el `data/movies.json` real, ni el `cache/` real, ni el `data/goya.db` real.

Una clase de test merece mención: los de la base de datos **insertan datos malos y exigen
que la base los rechace**. Una duración de `'105 años'`, una nominación de una película que
no existe, un `credited_kind` inventado, una clave natural duplicada, una persona que no
aparece en ninguna película. Comprobar que existen trece tablas no dice nada; comprobar
que el esquema impide el dato equivocado, sí.

**Los tests no usan internet.** Todo el HTML de ejemplo son ficheros reales guardados en
`tests/fixtures/`:

| Fixture | Qué cubre |
|---|---|
| `home.html` | El índice de las 40 ediciones con su año |
| `edicion_36_nominaciones.html` | Goya 2022: 28 categorías, 114 filas, 51 películas |
| `edicion_1_nominaciones.html` | Goya 1987: la primera edición, con los nombres de categoría antiguos |
| `pelicula_el-buen-patron.html` | 20 nominaciones, 6 premios, tres actores en una misma categoría |
| `pelicula_maixabel.html` | 14 nominaciones, 3 premios |
| `pelicula_otra-ronda.html` | La única con `Título original` ("Druk") |
| `pelicula_yalla.html` | Sin premios: el contador "Goyas" **desaparece** de la página |
| `error_404.html` | Página de error real, sin `article.pelicula` |

Si algún día cambia el sitio, se regeneran recortando a la zona útil:

```bash
curl -A "goya-scraper/0.1" -o /tmp/ed36.html \
  https://www.premiosgoya.com/36-edicion/nominaciones/

python3 - <<'PY'
h = open('/tmp/ed36.html', encoding='utf-8').read()
body = h[h.find('<div class="peliculas">'):h.find('<footer role="contentinfo">')]
open('tests/fixtures/edicion_36_nominaciones.html', 'w', encoding='utf-8').write(body)
PY
```

Las fichas se recortan igual, dejando solo el `<article class="pelicula">`. Así una
fixture se lee como un ejemplo y no como un volcado de 60 KB.

**Alternativa más cómoda:** como el scraper ya guarda todo el HTML en `cache/`, para
actualizar una fixture normalmente basta con copiarla de ahí y recortarla:

```bash
python3 - <<'PY'
h = open('cache/edicion_36_nominaciones.html', encoding='utf-8').read()
body = h[h.find('<div class="peliculas">'):h.find('<footer role="contentinfo">')]
open('tests/fixtures/edicion_36_nominaciones.html', 'w', encoding='utf-8').write(body)
PY
```

### Una trampa real del desarrollo de la Fase 2

Al escribir los tests se colaron **expectativas inventadas** en varios sitios: `133`
minutos en vez de `115`, un título de canción mal copiado, y una lista de nominados a
"Mejor película" que no correspondía a la edición 36. Los tests fallaron y la causa fue la
**expectación**, no el código.

Regla que salió de ahí: **un valor esperado se lee de la fixture, nunca de la memoria.**
Antes de escribir `assert x == "algo"`, imprimimos `x` y copiamos. Si ya sabías el valor de
memoria es porque lo has leído antes en la web, y la web puede haber cambiado.

Y al revés: cuando un test falla, **antes de tocar el código, comprueba la fixture.** Si
el HTML real dice otra cosa, el test es el que está mal.

### Una trampa peor, de la fase SQLite

Escribir un fichero largo de una vez produjo **bytes de control** dentro de varias
restricciones `CHECK`. Una tabla con un `CHECK` así habría creado el esquema, aceptado los
31 valores buenos y rechazado los malos: **parecería correcta hasta que llegaran datos
reales**, y el fallo aparecería semanas después sin causa aparente.

La lección es que `sqlite_master` no basta: leer el esquema y contar objetos no detecta un
`CHECK` dañado. Por eso los tests insertan datos malos de verdad. Y hay uno que **lee los
bytes** de `schema.sql` y falla si aparece un `\x00`, que es la forma que tomó aquí la
corrupción.

Además, escribir en trozos de unas 50 líneas verificando cada uno con
`Path(f).read_bytes()` evitó el problema. Y una prueba de integridad previa (un fichero
pequeño con `ñ`, tildes y símbolos) confirmó que el canal no era el problema: el tamaño sí.

---

## Estructura del proyecto

```
goya-scraper/
├── src/goya_scraper/      el paquete
│   └── schema.sql          el esquema, como fichero de texto
├── tests/
│   ├── fixtures/           HTML real, recortado
│   └── test_*.py
├── data/movies.json        el resultado del scraper (fuente de verdad, versionado)
├── data/goya.db            la copia consultable (se regenera, no se versiona)
├── cache/                  HTML crudo (no se versiona)
├── docs/                   esta documentación
├── AGENTS.md               reglas de trabajo e invariantes
├── LICENSE                 MIT
├── pyproject.toml
└── README.md
```

`cache/` y `data/goya.db` están en `.gitignore`: se regeneran y no aportan nada al
repositorio.

`data/movies.json`, en cambio, **sí está versionado**: es el resultado del proyecto y
permite consultar los datos sin esperar la descarga. El coste es que regenerarlo produce
un diff muy grande, así que ese cambio va en un commit propio y deliberado, nunca
mezclado con otra cosa. Ver la sección de estado en Git de [`AGENTS.md`](../AGENTS.md).

---

## Cómo probar a mano, sin esperar 35 minutos

Durante el desarrollo lo normal es no querer lanzar el histórico entero. Dos formas:

**Borrar la caché y ejecutar.** Si solo hay una edición cacheada, solo se procesa esa.

**Mirar el log.** Cada paso importante se registra:

```
[INFO] discovering editions from https://www.premiosgoya.com/
[INFO] found 40 editions (1987-2026)
[INFO] edition 36 already cached, skipping
[INFO] fetching edition 1 nominations
[INFO] edition 1: 15 categories, 44 nominations, 22 movies
[INFO] fetching movie: La vida secreta de las palabras
[WARNING] movie /pelicula/xyz: 404 not found
[ERROR] could not parse edition 7: missing section.categoria-de-peliculas
[INFO] done: 1 edition, 22 movies, 44 nominations, 15 awards
```

Los logs van a la salida estándar por defecto. Para más detalle:

```bash
python -m goya_scraper 2>&1 | tee log.txt
```

---

## Cómo añadir una funcionalidad

El orden que funciona mejor:

1. **Primero el test.** Escribe el test con el HTML que debería producir el resultado. Si
   no sabes cómoexpressar el resultado esperado, todavía no tienes claro el diseño.
2. **Después la función pura.** Sin `requests`, sin red.
3. **Después el cableado** en `run.py`.
4. **Después la documentación.**

Si te saltas el paso 1, acabarás con una función que no sabes si hace lo que crees.

### Añadir un campo nuevo

Para un campo que ya está en el HTML pero aún no se extrae, por ejemplo una etiqueta nueva
en el `dl` de la ficha:

1. Añade el test en `tests/test_parse_movie.py`.
2. Añade la etiqueta al mapa de `parse_movie.py`.
3. Añádelo al `Movie` y a `to_dict()` en `model.py`.
4. Actualiza `docs/data-model.md`.

Los `dt`/`dd` se recorren en bucle, así que una etiqueta nueva **no** necesita tocar el
parseo: basta con mapearla.

### Añadir un campo que no está en la fuente

Antes de nada, comprobar que está en el HTML. Si no está, **no lo implementes**: escribe
un ADR en `docs/decisions.md` explicando por qué no. Fue lo que hicimos con el año, los
géneros y las fuentes externas.

---

## estilo de código

Sin linter configurado a propósito (una dependencia más). Convenciones que sí seguimos:

- **Nombres en inglés** en el código, **documentación en español**.
- Docstrings en inglés, una línea, solo cuando no es obvio.
- Funciones cortas. Si superas las ~40 líneas, probablemente hay dos funciones.
- Los comentarios explican **por qué**, no **qué**. El qué ya está en el código.
- Constantes en mayúsculas y agrupadas arriba (`DEFAULT_TIMEOUT`, `MIN_INTERVAL`, …).

---

## Ver el informe de validación

Sale solo al final de cada ejecución. Para relanzarlo sobre el fichero sin volver a
scrapear:

```python
from goya_scraper import storage
from goya_scraper.validate import validate, render

print(render(storage.load(), validate(storage.load())))
```

Y el de la base de datos, igual de simple:

```python
from goya_scraper import db, db_validate, storage

document = storage.load()
connection = db.connect("data/goya.db")
print(db_validate.validate(connection, document).render())
```

## Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| `ModuleNotFoundError: goya_scraper` | No instalaste el paquete. `pip install -e .` |
| `error: externally-managed-environment` | Tu Python del sistema está protegido (PEP 668). Crea un `.venv`; es lo que hace `development.md`. |
| Los tests fallan todos de golpe | Cambió el HTML del sitio. Compara `cache/` con `tests/fixtures/`. |
| Se repite una descarga que creías cacheada | No existe el fichero. Mira si `cache/` se borró. |
| La segunda ejecución tarda lo mismo que la primera | Estás haciendo `rm -rf cache/` sin querer, o el `cache_dir` no apunta al sitio. Mira `[INFO] cache hit`. |
| `403` o `429` en el log | El sitio está limitando. **Para.** No es un bug que haya que sortear. |
| `CorruptDocumentError` | `data/movies.json` está roto. Arréglalo o bórralo; no se sobrescribe solo. |
| El JSON sale vacío | Ninguna edición se pudo procesar. Mira los `ERROR` del log. |
| `STRICT tables need SQLite 3.37` | El SQLite del sistema es antiguo. `db.create_database` se niega en vez de crear un esquema sin garantías de tipo. |
| `cannot store TEXT value in INTEGER column` | `STRICT` funcionando: alguien intentó meter texto en `duration_minutes`. |
| `FOREIGN KEY constraint failed` al importar | El documento tiene una nominación de una edición o película que no existe. `db_validate` lo señala. |
| `categoria sin credited_kind` | La Academia añadió un premio. Añádelo a `credited_kinds.py` con su tipo de crédito y reimporta; el importador **se niega** a adivinar. |
| La base de datos quedó vacía tras un fallo | Es lo esperado: `import_db` borra el fichero antes de escribir. Vuelve a ejecutarlo. |
