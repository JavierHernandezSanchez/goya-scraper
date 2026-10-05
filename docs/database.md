# La base de datos

## Qué es y qué no es

`data/goya.db` es una **copia consultable** de `data/movies.json`. El JSON sigue siendo la
fuente de verdad: la base de datos se reconstruye desde él y nunca se escribe a mano.

```
Web Goya → scraper → model → storage → data/movies.json
                                            ↓
                                      import_db → data/goya.db
```

El scraper **no sabe que existe la base de datos**. Hay un test que lo comprueba
(`test_the_scraper_does_not_import_the_database`): importar `run.py` no carga el módulo
`db`, y si algún día lo cargara, el test fallaría.

---

## Puesta en marcha

```bash
.venv/bin/python -m goya_scraper              # baja los datos (lento, ~35 min con caché)
.venv/bin/python -m goya_scraper.import_db     # movies.json -> goya.db
.venv/bin/python -m goya_scraper.db_validate  # comprueba una contra el otro
```

Ambas órdenes aceptan rutas opcionales:

```bash
python -m goya_scraper.import_db data/movies.json data/goya.db
```

Y para consultar:

```bash
sqlite3 data/goya.db
```

---

## El esquema

Trece tablas, diez índices, una vista. El esquema completo está en
[`src/goya_scraper/schema.sql`](../src/goya_scraper/schema.sql), que es un fichero de
texto normal y funciona también como script:

```bash
sqlite3 data/goya.db < src/goya_scraper/schema.sql
```

### Las tres entidades centrales

```
goya_edition  ─┐
category      ─┼─→ nomination ─→ film
movie         ─┘        │
                        └─→ nomination_credit ─→ person (a veces)
```

`nomination` es el corazón: una fila es **una película compitiendo por un premio en una
edición**. Es lo que el JSON tenía anidado dentro de cada película, y es lo que hace
consultable el premio sin recorrer 1678 objetos.

### Todas las tablas

| Tabla | Filas | Qué guarda |
|---|---:|---|
| `goya_edition` | 40 | Número de edición y año de ceremonia |
| `category` | 31 | Nombre canónico y qué contiene su columna `credited` |
| `country` | 48 | Países, con las erratas de la fuente |
| `movie` | 1678 | Slug, títulos, duración, texto de productores, estado de la ficha |
| `person` | 6033 | Una fila por persona real |
| `person_alias` | 6130 | Cada grafía de la fuente y a qué persona apunta |
| `movie_credit` | 10389 | Película ↔ persona con rol (`director`, `screenwriter`, `cast`) |
| `movie_country` | 1861 | Película ↔ país |
| `nomination` | 4050 | Película × edición × categoría, con `won` y `note` |
| `nomination_credit` | 5277 | A quién se acredita esa nominación |
| `reported_award` | 1027 | Lo que **la ficha** dice que ganó, aparte de lo que dice la edición |
| `dataset_meta` | 1 | Qué JSON generó esta base de datos |
| `import_run` | 1 por ejecución | Cuándo, con qué hash, y qué se escribió |

### Relaciones

```
Movie       1 ──── N  Nomination        1678 → 4050
GoyaEdition 1 ──── N  Nomination           40 → 4050
Category    1 ──── N  Nomination           31 → 4050
Nomination  1 ──── N  NominationCredit   4050 → 5277
Person      o ──── N  NominationCredit        → 3922   (NULL en las otras 1355)

Movie       N ──── N  Person            vía movie_credit
Movie       N ──── N  Country           vía movie_country
```

Tres relaciones son muchos-a-muchos de verdad: una persona aparece en muchas películas y en
muchas nominaciones, y una película tiene muchas personas. Ninguna se puede resolver con
una clave foránea en `movie`.

---

## Decisiones del modelo

### Claves: surrogate con la identidad del servidor como restricción

`movie.id` es un entero que asigna el importador. `movie.slug` es lo que dio el servidor.
El slug **puede cambiar**; el entero no. Lo mismo con `country.id`: los nombres traen
erratas de la fuente (`Fancia`, `Polinia`), así que el nombre es una etiqueta y el id es
la clave.

El **título nunca identifica**. Doce títulos del dataset son de dos slugs distintos:
`alma`/`alma-2`, `roma`/`roma-2`, `madre`/`madre-2`, `Cuerdas` tiene tres.

### No existe una tabla `award`

Ganar es una **columna** de `nomination`, no una entidad. En este dataset una nominación
*es* el hecho, y la razón está en los datos:

| Caso | Cuántos |
|---|---:|
| Ediciones con empate | 4 (una con tres ganadoras) |
| Categorías sin ganador marcado | 3 |

Una tabla `award` con `UNIQUE (edition_id, category_id)` **no podría contener eso**.

### La nominación necesita un id propio

`(película, edición, categoría)` **no es única**: 46 ternas se repiten de verdad. En
*Alcarràs*, edición 37, competing por Mejor actor revelación, hay dos nominaciones, una
por cada actor.

La clave natural real incluye los créditos, y eso es lo que hace `credit_fingerprint`:

```sql
CREATE UNIQUE INDEX nomination_natural_key
    ON nomination (movie_id, edition_id, category_id, credit_fingerprint);
```

- Categoría de persona → `"p:123|p:45"` (los `person_id`, no los nombres, para que
  corregir una grafía no cambie la clave)
- Categoría de obra → `"t:Dolor|t:gloria"` (el texto literal)

Verificado sobre los datos reales: **4050 filas, cero rechazos**. Una doble importación
falla en vez de duplicar.

### `credited` significa tres cosas distintas

La columna que el sitio llama "acreditado" contiene, según la categoría:

| Tipo | Categorías | Créditos | Qué es |
|---|---:|---:|---|
| `person` | 20 | 3922 | Nombre de una persona |
| `work` | 10 | 1158 | El título de la propia película |
| `song` | 1 | 197 | `"<canción> - Compositores: <nombres>"` |

Está en `category.credited_kind` porque **no se puede adivinar**. La prueba: *Carmen y
Lola* aparece acreditada como `["Carmen", "Lola"]` y existe una película llamada *Carmen*.

Medido sobre las 4050 nominaciones reales: **cero inconsistencias**. Ninguna categoría de
persona acredita un título; ninguna de obra acredita un nombre.

Por eso `nomination_credit` guarda siempre `credit_text` (el literal) y llena
`person_id` **solo** cuando la categoría es de tipo `person`. En las 1355 filas de obra y
canción queda `NULL`.

### Las personas no se duplican

6130 grafías distintas colapsan en **6033 personas** mediante 90 grupos curados a mano en
`persons.py`. La razón de que sea una tabla escrita y no una función está medida:

| Grafía | Frecuencia | ¿Correcta? |
|---|---:|---|
| `Iciar Bollain` | 34 | no, sin tildes |
| `Icíar Bollaín` | 5 | sí |
| `Tina Sáinz` | 4 | no, `Sainz` es lo correcto |
| `José Luís Quirós` | 2 | no, una `l` por `ll` |

Y **25 de los 90 grupos son empates exactos de frecuencia**: los datos no pueden
desempatarlos.

Lo que sí es una regla es *agrupar*: dos grafías son el mismo grupo solo si son **iguales**
(no parecidas) tras normalizar Unicode, quitar acentos, colapsar espacios e ignorar
guiones y apóstrofos. Eso es una igualdad demostrable, no una conjetura.

`person_alias` guarda cada grafía tal cual, lo que hace la fusión **reversible**: borrar
una fila devuelve a dos personas, sin tocar código.

### No se duplica lo que ya está en `movie`

Once campos del JSON **no** se importan:

| Campo del JSON | Por qué |
|---|---|
| `url` | Derivado de `slug` |
| `goya.editions` | Derivado; hoy siempre vale `[único]` |
| `goya.total_nominations` | La vista `movie_totals` lo recalcula |
| `goya.total_awards` | Ídem |
| `data_quality.missing_fields` | Verificado: es exactamente `{campo IS NULL}` |
| `data_quality.issues` | Siempre `[]` en las 1678 |

Una columna derivable es una **segunda verdad** que puede divergir de la primera sin que
nada se entere.

**La excepción deliberada:** `movie.reported_nominations` y `movie.reported_awards` **sí**
se guardan, y `reported_award` es tabla aparte. No son el mismo hecho: son dos fuentes
independientes que hay que poder comparar. El dataset contiene 6 películas donde discrepan.

### Tres estados de ausencia, nunca uno

| Estado | En la base de datos | Ejemplo real |
|---|---|---|
| La ficha no se pudo leer | `reported_awards IS NULL` | — |
| La ficha dijo que no ganó nada | `reported_awards = 0`, sin filas en `reported_award` | *El rey de la granja* |
| No hay datos de la ficha en absoluto | Cero filas | 55 películas sin país |

Un `CHECK` lo blinda:

```sql
CHECK ((detail_status = 'ok') = (reported_awards IS NOT NULL))
```

Un `0` ahí significaría "la web afirma que no ganó nada", que es una afirmación distinta de
"no lo sabemos". *El rey de la granja* y *Puerta del tiempo* dicen 0 y la edición las
premió.

### `producers_raw` es un string opaco

No hay tabla de productoras. El texto trae comas internas y gente dentro:

```
"Lastor Media(Sergi Moreno,Tono Folguera Amorós), La Panda Productions(Jana Díaz Juhl)"
```

Un split ingenuo rompe **los 297 valores con paréntesis, el 100%**. Partirlo sería
inventar datos.

### `STRICT` en todas las tablas

SQLite es de tipado dinámico: sin `STRICT`, guardaría el texto `'105 años'` en una columna
de duración sin decir nada. Con `STRICT` falla al insertar. Necesita SQLite 3.37+; el
módulo se niega a funcionar con una versión anterior en vez de degradarse en silencio.

---

## Índices

| Índice | Para qué consulta |
|---|---|
| `nomination(movie_id)` | Nominaciones de una película |
| `nomination(category_id, edition_id)` | Quién compitió en un premio |
| `nomination(edition_id)` | Evolución por año |
| `nomination … WHERE won = 1` **(parcial)** | Solo hay 1027 ganadoras de 4050: cuatro veces más pequeño |
| `movie_credit(person_id)` | En qué películas sale una persona |
| `nomination_credit(person_id)` | Premios de una persona |
| `movie_country(country_id)` | Películas de un país |
| `movie(title)` | Búsqueda por título (índice normal, **no** `UNIQUE`) |
| `person_alias(person_id)` | Auditar las fusiones de nombres |
| `nomination_natural_key` **`UNIQUE`** | Que una doble importación falle |

**Lo que deliberadamente no se indexa:** `movie.slug`, `person.name`, `category.name`,
`country.name` y `goya_edition.number` ya son `UNIQUE`, y SQLite les crea índice. Y
`movie_credit(movie_id)` tampoco: la clave primaria `(movie_id, person_id, role)` ya
responde a esa búsqueda por su prefijo izquierdo.

---

## Consultas

### Las películas con más premios

```sql
SELECT m.title, t.total_nominations, t.total_awards
FROM movie_totals t JOIN movie m ON m.id = t.movie_id
ORDER BY t.total_awards DESC, t.total_nominations DESC LIMIT 15;
```

```
Mar adentro          15 nominaciones, 14 premios
¡Ay, Carmela!        15, 13
La sociedad de la nieve  13, 12
Blancanieves         18, 10
```

### Nominadas mucho y sin ganar nada

```sql
SELECT m.title, t.total_nominations
FROM movie_totals t JOIN movie m ON m.id = t.movie_id
WHERE t.total_awards = 0 AND t.total_nominations >= 5
ORDER BY t.total_nominations DESC LIMIT 10;
```

### Directores con más Goya

Aquí está el fruto de `credited_kind`: el rol **no se escribe**, se deduce de la categoría.

```sql
SELECT p.name, COUNT(*) AS goyas
FROM nomination n
JOIN nomination_credit nc ON nc.nomination_id = n.id
JOIN person p ON p.id = nc.person_id
JOIN category c ON c.id = n.category_id
WHERE n.won = 1 AND c.name IN ('Mejor dirección', 'Mejor dirección novel')
GROUP BY p.id ORDER BY goyas DESC, p.name LIMIT 10;
```

```
Fernando León de Aranoa  4
J.A. Bayona              4
Alejandro Amenábar       3
Pedro Almodóvar          3
```

### Actores con más películas

```sql
SELECT p.name, COUNT(DISTINCT mc.movie_id) AS peliculas
FROM movie_credit mc JOIN person p ON p.id = mc.person_id
WHERE mc.role = 'cast'
GROUP BY p.id ORDER BY peliculas DESC LIMIT 10;
```

### Ganadoras de Mejor película por año

Sin `GROUP BY` y sin lógica de desempate. En 2014 y 2025 salen **dos filas**, que es lo
correcto.

```sql
SELECT e.ceremony_year, m.title
FROM nomination n
JOIN movie m ON m.id = n.movie_id
JOIN goya_edition e ON e.id = n.edition_id
JOIN category c ON c.id = n.category_id
WHERE c.name = 'Mejor película' AND n.won = 1
ORDER BY e.ceremony_year;
```

### El equipo técnico que solo existe por las nominaciones

Esta consulta justifica `nomination_credit`. La ficha no tiene campo para sonido,
fotografía ni vestuario, así que **910 personas no aparecen en ningún sitio más**.

```sql
SELECT p.name, c.name AS premio, COUNT(*) AS veces
FROM nomination_credit nc
JOIN person p ON p.id = nc.person_id
JOIN nomination n ON n.id = nc.nomination_id
JOIN category c ON c.id = n.category_id
WHERE NOT EXISTS (SELECT 1 FROM movie_credit mc WHERE mc.person_id = p.id)
GROUP BY p.id, c.id ORDER BY veces DESC LIMIT 10;
```

```
Reyes Abades        Mejores efectos especiales   42
Raúl Romanillos     Mejores efectos especiales   25
José Luis Alcaine   Mejor dirección de fotografía 21
Alberto Iglesias   Mejor música original         19
```

### Evolución del número de nominaciones

```sql
SELECT e.ceremony_year, COUNT(*) AS nominaciones, SUM(n.won) AS premios,
       COUNT(DISTINCT n.movie_id) AS peliculas
FROM goya_edition e JOIN nomination n ON n.edition_id = e.id
GROUP BY e.id ORDER BY e.number;
```

El salto de 114 a 141 nominaciones entre 2022 y 2023 se ve directo: la Academia añadió
categorías.

### Empates y categorías sin ganador

```sql
SELECT e.ceremony_year, c.name, SUM(n.won) AS ganadores
FROM nomination n
JOIN goya_edition e ON e.id = n.edition_id
JOIN category c ON c.id = n.category_id
GROUP BY e.id, c.id HAVING SUM(n.won) <> 1;
```

### Los créditos rotos, visibles

```sql
SELECT m.title, nc.credit_text
FROM nomination_credit nc
JOIN nomination n ON n.id = nc.nomination_id
JOIN category c ON c.id = n.category_id
JOIN movie m ON m.id = n.movie_id
WHERE c.credited_kind = 'work' AND nc.credit_text <> m.title LIMIT 10;
```

```
Dolor y gloria         → 'Dolor', 'gloria'
Carmen y Lola          → 'Carmen', 'Lola'
15 años y un día        → '15 años', 'un día'
```

El dato está **guardado y consultable**, pero nadie lo trata como una entidad. Por eso
`nomination_credit` no tiene clave foránea a `movie`: 8 de esos fragmentos coinciden con
el título de **otra** película y cualquier unión sería falsa.

### Auditar las fusiones de nombres

```sql
SELECT p.name AS persona, GROUP_CONCAT(a.alias, ' / ') AS grafias,
       (SELECT COUNT(*) FROM movie_credit mc WHERE mc.person_id = p.id) AS peliculas
FROM person p JOIN person_alias a ON a.person_id = p.id
GROUP BY p.id HAVING COUNT(*) > 1 ORDER BY p.name LIMIT 10;
```

---

## Validación

```bash
python -m goya_scraper.db_validate
```

Devuelve `1` si hay errores, `0` si solo hay avisos o información. Comprobaciones:

| Qué | Cómo |
|---|---|
| Recuentos JSON ↔ SQLite | 9 tablas una a una |
| Ganadoras coherentes | `SUM(won)` y la vista `movie_totals` |
| Sin claves foráneas huérfanas | `PRAGMA foreign_key_check` |
| Sin duplicados | slug, nombres, alias |
| Toda nominación tiene película, edición y categoría | `LEFT JOIN` a mano |
| Todo tiene identificador | `id` y `slug` no nulos |
| Integridad del fichero | `PRAGMA integrity_check` |

Sobre los datos reales:

```
0 errores, 2 avisos, 4 informacion
```

Los **4 avisos e información no son nuestros fallos**, son historia de la Academia:

- 4 categorías con empate (una con tres ganadoras)
- 3 categorías sin ganador marcado
- 6 películas donde la ficha y la edición discrepan
- 218 créditos de obra que no son el título exacto

Los 2 avisos: 46 película/edición/categoría con más de una nominación (esperado: dos
actores pueden competir) y 2 películas cuya ficha dice 0 premios mientras la edición premia.

---

## Reproducibilidad

La importación **reconstruye** la base de datos entera dentro de una transacción
`BEGIN IMMEDIATE`:

- **Reproducible**: importar dos veces el mismo JSON da el mismo archivo. Los ids los
  asigna el importador en orden de `slug` + `category` + `edition`, nunca SQLite.
- **Atómica dentro de sí misma**: un fallo deshace todas las filas de esa ejecución.
- **Lo que NO protege**: el fichero anterior. `create_database` lo borra antes de
  escribir, así que tras un fallo queda una base válida pero **vacía**. La recuperación es
  reimportar, que es justo por lo que todo es un único comando reproducible.

`import_run.json_sha256` responde "¿esta base salió del JSON que tengo ahora?".

---

## Lo que el modelo no puede responder

| Pregunta | Por qué |
|---|---|
| ¿De qué género es cada película? | **El dato no existe en la fuente.** No hay tabla de género porque no hay género |
| ¿Qué productoras hay, separadas? | `producers_raw` es un string indivisible |
| ¿En qué año se estrenó cada película? | La fuente no lo tiene y no se deriva |
| ¿Quién compuso esa canción? | El crédito mezcla canción y compositores en un string |
| ¿Con quién está casado X? | La fuente no da esa información |
