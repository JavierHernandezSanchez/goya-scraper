# Modelo de datos

Qué significa cada campo de `data/movies.json` y por qué está así.

Los nombres de campo y las reglas de normalización derivan de los datos reales medidos
sobre las 40 ediciones y 173 fichas de película. Ver `decisions.md` para el porqué de cada
elección.

---

## Estructura de nivel superior

El fichero es un **objeto**, no una lista pelada:

```json
{
  "_meta": { ... },
  "movies": [ ... ]
}
```

**Por qué el envoltorio.** Necesitamos guardar en algún sitio qué ediciones se han
procesado ya; es lo que hace posible la incrementalidad (ADR-010). Además `schema_version`
avisa de si el formato ha cambiado, y `counts` permite validar sin recorrer el fichero.

Orden de las claves dentro de cada objeto: fijo y significativo, no alfabetico. El JSON se
escribe con `indent=2` y `ensure_ascii=False` para que los acentos se lean bien.

---

## `_meta`

```json
"_meta": {
  "schema_version": 2,
  "source": "https://www.premiosgoya.com",
  "generated_at": "2026-10-03T22:45:12Z",
  "editions_scraped": [1, 2, 36],
  "counts": {
    "editions": 3,
    "movies": 58,
    "nominations": 111,
    "awards": 28,
    "distinct_categories": 28
  }
}
```

| Campo              | Tipo        | Significado                                                                 |
| ------------------ | ----------- | --------------------------------------------------------------------------- |
| `schema_version`   | `int`       | Versión de este documento. Ahora mismo **2**. Sube si cambia la estructura. |
| `source`           | `str`       | Único dominio del que proceden los datos (ADR-001).                         |
| `generated_at`     | `str`       | Fecha y hora de la última escritura, formato ISO 8601 UTC.                  |
| `editions_scraped` | `list[int]` | Ediciones ya descargadas. Base de la incrementalidad.                       |
| `counts`           | `obj`       | Totales del fichero. Se recalculan en cada escritura.                       |

`counts` **no es una caché**: se deriva siempre de `movies` al escribir. Si alguien lo
edita a mano, la siguiente ejecución lo sobrescribe.

---

## Una película

```json
{
  "slug": "el-buen-patron",
  "url": "https://www.premiosgoya.com/pelicula/el-buen-patron",
  "title": "El buen patrón",
  "title_original": null,
  "synopsis": "Walter, chef de un restaurante de alta cocina...",
  "countries": ["España"],
  "countries_raw": "Española",
  "duration_minutes": 133,
  "credits": {
    "directors": ["Fernando León de Aranoa"],
    "screenwriters": ["Fernando León de Aranoa"],
    "cast": ["Javier Bardem", "Manolo Solo"],
    "producers_raw": "Bambú Producciones, Telefe Spain"
  },
  "goya": {
    "editions": [36],
    "total_nominations": 20,
    "total_awards": 6,
    "nominations": [ ... ]
  },
  "data_quality": {
    "detail_status": "ok",
    "reported_by_source": { "nominations": 20, "awards": 6 },
    "missing_fields": ["title_original"],
    "issues": []
  }
}
```

### Identidad

| Campo   | Tipo            | Notas                                                                                                       |
| ------- | --------------- | ----------------------------------------------------------------------------------------------------------- |
| `slug`  | `str`           | **Clave primaria.** El identificador que da el servidor (ADR-002).                                          |
| `url`   | `str`           | URL absoluta de la ficha, construida a partir del `slug`. Se guarda para que el fichero sea autosuficiente. |
| `title` | `str` \| `null` | El `<h1>`. Es `null` solo si no se pudo leer la ficha; entonces `detail_status` lo explica (ADR-014).       |

Sobre `title`: en los datos reales de las 1678 películas **nunca** ha hecho falta. Existe
únicamente para que un fallo de red no borre las nominaciones de una película.

### Ficha

Todos estos campos vienen de la **ficha de película** (`/pelicula/{slug}/`). El
porcentaje indica con qué frecuencia la fuente los tiene, medido sobre 173 películas reales.

| Campo              | Tipo            | Presente | Origen / normalización                                                       |
| ------------------ | --------------- | -------- | ---------------------------------------------------------------------------- |
| `title`            | `str`           | 100%     | El `<h1>` de la ficha.                                                       |
| `title_original`   | `str` \| `null` | 60%      | Difiere del `title` en el 22% de los casos, así que aporta información real. |
| `synopsis`         | `str` \| `null` | 99%      | Texto de `pelicula__header__sinopsis`.                                       |
| `countries`        | `list[str]`     | 98%      | Normalizado. Ver abajo.                                                      |
| `countries_raw`    | `str` \| `null` | 98%      | Valor literal de la fuente. **Se conserva siempre.**                         |
| `duration_minutes` | `int` \| `null` | 30%      | La fuente dice `"105 minutos"`; se extrae el entero.                         |
| `credits`          | `obj`           | —        | Ver abajo.                                                                   |

### `countries`: el caso más delicado

El campo `Nacionalidad` de la fuente es texto libre y **con género gramatical**. Valores
reales encontrados:

```
"España"                            68 veces
"Española"                          59 veces   <-- se refiere a la PELÍCULA, no al país
"España, Francia"                    4 veces
"Dinamarca/Suecia"                   1 vez     <-- separador /
"España, Francia y Portugal"         1 vez     <-- separador " y "
"Francia/Bélgica/España"             1 vez
```

Regla de normalización (implementada en `model.py` y testada):

1. Sustituir `/` por `,`.
2. Partir por `,`, y luego por ` y ` / ` e ` en cada trozo.
3. Aplicar un **alias explícito** y pequeño: `{"Española": "España"}`.
4. Quitar espacios sobrantes, eliminar duplicados conservando el orden.
5. Lo que no se reconoce **se conserva tal cual**. No se descarta ni se adivina.

`countries_raw` conserva el valor original, así que la normalización es siempre
reversible y auditable. Ese es el patrón que usamos en todo el proyecto: **el dato
normalizado para usar, el dato crudo para poder comprobar.**

### `credits`

| Campo           | Tipo            | Presente | Normalización                          |
| --------------- | --------------- | -------- | -------------------------------------- |
| `directors`     | `list[str]`     | 99%      | Separada por `,` / ` y ` / ` e `       |
| `screenwriters` | `list[str]`     | 77%      | Igual                                  |
| `cast`          | `list[str]`     | 73%      | Igual                                  |
| `producers_raw` | `str` \| `null` | 86%      | **Sin separar**, a propósito (ADR-008) |

`producers_raw` es una cadena, no una lista, y el nombre lo dice. Los nombres de empresa
contienen comas internas (`"Alba Sotorra, S.L."`), así que separarlas produciría datos
falsos. Preferimos no parsear antes que parsear mal.

Todos los campos de persona se deduplican conservando el orden. Eso arregla de paso
casos como `"Thomas Vinterberg, Thomas Vinterberg"`, que aparecen en la fuente.

Un aviso honesto sobre la separación de nombres: el separador ` y ` se usa en la fuente
como conjunción, pero un nombre propio podría contenerlo. El riesgo es asimétrico y
aceptamos el lado bueno: separar de más es mucho menos dañino que no separar.

### `goya`

| Campo               | Tipo        | Significado                                                       |
| ------------------- | ----------- | ----------------------------------------------------------------- |
| `editions`          | `list[int]` | Ediciones en las que compite. Dato de la **página de edición**.   |
| `total_nominations` | `int`       | Número de filas de nominación. Coincide con lo que dice la ficha. |
| `total_awards`      | `int`       | Número de nominaciones con `won: true`.                           |
| `nominations`       | `list[obj]` | El detalle. Ver abajo.                                            |

Sobre `editions`: con los datos reales **ninguna película compite en dos ediciones**
(comprobado en las 1678). El campo sigue siendo una lista porque el modelo lo permite y
porque no cuesta nada; simplemente hoy siempre tiene un elemento.

**No** almacenamos `ceremony_year` en este nivel: es derivable (`edición + 1986`) y está
en cada nominación. Guardar datos derivados duplicados es una forma de que se
desincronicen sin que nadie se entere.

Tampoco almacenamos `distinct_categories`. Se calcula cuando haga falta con
`len({n["category"] for n in nominations})`. Es una decisión deliberada: los campos
derivados que se guardan son los que hacen falta para consultar; el resto se calcula.

### Una nominación

```json
{
  "edition": 36,
  "ceremony_year": 2022,
  "category": "Mejor actor de reparto",
  "credited": ["Celso Bugallo"],
  "won": false,
  "note": "Por El buen patrón"
}
```

| Campo           | Tipo            | Significado                                                                                        |
| --------------- | --------------- | -------------------------------------------------------------------------------------------------- |
| `edition`       | `int`           | Número de edición (36).                                                                            |
| `ceremony_year` | `int`           | Año de la ceremonia. **Leído de la fuente**, no calculado: el bloque de años del sitio lo publica. |
| `category`      | `str`           | Nombre canónico de la categoría (ADR-022).                                                         |
| `category_raw`  | `str`           | Lo que escribió la web ese año. **Siempre presente**, incluso si no cambia.                        |
| `credited`      | `list[str]`     | Nombre acreditado, separado si son varias personas.                                                |
| `won`           | `bool`          | Si esa fila ganó. Del `img[title^="Ganadora"]` (ADR-006).                                          |
| `note`          | `str` \| `null` | Texto auxiliar de la web.                                                                          |

Sobre las categorías: el sitio usa el nombre que estaba en vigor ese año, y la Academia
renombró dos premios a lo largo de 40 años. Guardamos el nombre canónico en `category` y el literal en `category_raw`, así que el catálogo se puede consultar por el nombre actual sin
perder nada de lo que dijo la fuente:

```json
{
  "edition": 24,
  "ceremony_year": 2010,
  "category": "Mejor dirección de arte",
  "category_raw": "Mejor dirección artística",
  "credited": ["Guy Hendrix Dyas"],
  "won": true,
  "note": "Por Agora"
}
```

El catálogo tiene **31 nombres canónicos** frente a las 33 etiquetas del sitio. Dos se
fusionan por renombrado verificado, y dos etiquetas históricas se conservan tal cual porque
la fuente nunca dice a cuál de las actuales corresponderían.

Dos aclaraciones sobre `credited`, porque es contraintuitivo:

- **En algunas categorías el acreditado no es una persona.** En "Mejor película" el
  acreditado es el propio título de la película (`"El buen patrón"`). El campo refleja lo
  que la fuente muestra, sin reinterpretarlo.
- **Una película puede tener varias filas en la misma categoría.** *El buen patrón* tiene
  tres nominaciones a "Mejor actor de reparto", una por actor. Por eso
  `total_nominations` son 20 filas y no 17 categorías (ADR-007).

`note` contiene el texto de `lista-de-peliculas__texto`. Su significado varía según la
categoría: en "Mejor película" son las productoras (información valiosa), en el resto suele
ser `"Por {título de la película}"` (redundante, pero se conserva).

El orden de `nominations` es **el de la página de origen**, que ya viene agrupado por
categoría. No reordenamos: no aporta nada y sería una transformación gratuita.

### `data_quality`

Existe para poder distinguir lo que pediste en el punto 12: **dato encontrado**, **dato no
encontrado** y **error al obtener el dato**.

| Campo                       | Tipo                           | Significado                                                                                                                 |
| --------------------------- | ------------------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| `detail_status`             | `str`                          | `ok` = ficha leída. `not_found` = el servidor devolvió 404 o la página no era una ficha. `error` = fallo de red o HTTP 5xx. |
| `reported_by_source`        | `obj` \| `null`                | Lo que declara la propia ficha. **`null` si `detail_status` no es `ok`**, para que un fallo no parezca "la web dice cero".  |
| `reported_award_categories` | dentro de `reported_by_source` | Las categorías que la ficha dice haber ganado. Permite nombrar el conflicto (ADR-020).                                      |
| `missing_fields`            | `list[str]`                    | Campos del esquema que no estaban en la ficha. Permite filtrar "películas sin duración".                                    |
| `issues`                    | `list[str]`                    | Anomalías detectadas al procesar esta película.                                                                             |

`reported_by_source` es lo que hace posible la validación cruzada sin ninguna petición
extra: si `total_nominations` no coincide con lo que declara la ficha, algo está mal y hay
que mirarlo. Es un control de calidad gratis (ADR-012).

Y `reported_award_categories` va un paso más allá. Con solo el número, el informe solo puede
decir "aquí hay una diferencia de 1". Con la lista de categorías puede decir **cuál**:

```
award_claimed_only_by_movie_page: [la-nina-de-tus-ojos]
  la ficha se atribuye ['Mejor actor revelación']
  pero no hay ganador marcado en la página de la edición
```

Eso es accionable sin salir del JSON (ADR-020).

---

## Campos que deliberadamente NO existen

| Campo                                                                      | Por qué no                                                                                                                                                                                |
| -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `release_year`                                                             | La fuente no lo tiene. Decidido no derivarlo (ADR-003).                                                                                                                                   |
| `release_date`                                                             | Igual.                                                                                                                                                                                    |
| `genres`                                                                   | No aparece en ninguna parte del sitio.                                                                                                                                                    |
| `budget`, `box_office`                                                     | No aparecen en ninguna parte del sitio.                                                                                                                                                   |
| `imdb_rating`, `rotten_tomatoes_rating`, `filmaffinity_rating`, `external` | Fuentes externas descartadas (ADR-004). El hueco se documenta en `sources.md`.                                                                                                            |
| `cinematographer`, `editor`, `composer`                                    | La web no los expone como campos. Se pueden intuir leyendo los nominees de "Mejor dirección de fotografía", pero eso sería **inventar** una relación que la fuente no afirma. No se hace. |
| `genre` (en la base de datos)                                              | Igual que `genres` en el JSON: no existe el dato, así que no existe la tabla. Una tabla de géneros vacía sería un modelo que inventa el dominio.                                          |
| `production_company` (en la base de datos)                                 | `producers_raw` es un string indivisible: los 297 valores con paréntesis se rompen todos con un split por comas, y el texto mezcla empresas con personas (ADR-033).                       |

Que no estén en el esquema es intencionado y es información: dice "esto no lo tenemos",
no "esto está vacío".

---

## Cómo se traduce este modelo a SQLite

`movies.json` es un documento centrado en la película; la base de datos es un modelo
relacional normalizado. El detalle completo está en [`database.md`](database.md); aquí solo
el mapa, para saber qué pasó con cada cosa.

| En el JSON                                           | En SQLite                                                                                                                   |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `slug`                                               | `movie.slug` con `id` surrogate. **El título nunca identifica**: doce títulos son de dos slugs                              |
| `url`                                                | No se guarda. Se deriva de `slug`                                                                                           |
| `title_original`, `synopsis`, `duration_minutes`     | Columnas de `movie`                                                                                                         |
| `credits.producers_raw`, `countries_raw`             | Columnas de `movie`, sin separar                                                                                            |
| `countries[]`                                        | Tabla `movie_country` (N:M con `country`)                                                                                   |
| `credits.directors` / `screenwriters` / `cast`       | Tabla `movie_credit`, con `role` **dentro de la clave primaria** porque 1153 personas tienen dos roles en la misma película |
| `goya.nominations[]`                                 | Tabla `nomination`, una fila por película × edición × categoría                                                             |
| `nominations[].credited[]`                           | Tabla `nomination_credit`, con `person_id` **nulo** en 1355 de las 5277 filas                                               |
| `goya.editions`, `total_nominations`, `total_awards` | No se guardan. Se derivan; la vista `movie_totals` los recalcula                                                            |
| `data_quality.missing_fields`, `issues`              | No se guardan. `missing_fields` está verificado como `{campo IS NULL}`                                                      |
| `data_quality.reported_by_source`                    | `movie.reported_nominations` / `reported_awards` **y** tabla `reported_award`                                               |
| `ceremony_year`                                      | Sube a `goya_edition.ceremony_year`, no se repite 4050 veces                                                                |
| `category`                                           | `category.id`, con `credited_kind` al lado                                                                                  |
| `category_raw`                                       | `nomination.category_raw`, por fila                                                                                         |
| Nombres de persona                                   | `person` + `person_alias`; 6130 grafías colapsan en 6033 personas                                                           |

### Lo que la base de datos aporta y el JSON no

- **La nominación tiene identidad.** Anidada en el JSON, no se puede consultar sin recorrer
  1678 objetos; en SQL son 4050 filas.
- **Las personas no se duplican.** En el JSON el mismo nombre aparece repetido en 11 mil
  sitios; en la base son 6033 filas con su lista de grafías.
- **Las consultas se pueden expresar.** "Directores con más Goya" es un `GROUP BY` con un
  filtro de categoría, no un recorrido del árbol.
- **La integridad la vigila el motor.** Claves foráneas, `CHECK`, `UNIQUE` y `STRICT` lo
  impiden en vez de avisar después.

### Lo que la base de datos no puede responder

| Pregunta                              | Por qué                                         |
| ------------------------------------- | ----------------------------------------------- |
| ¿De qué género es esta película?      | No está en la fuente                            |
| ¿Qué productoras hay, separadas?      | El string es indivisible                        |
| ¿En qué año se estrenó cada película? | No está en la fuente y no se deriva             |
| ¿Quién compuso esa canción?           | El crédito mezcla la canción y sus compositores |

---

## Tipos y reglas transversales

- **Todo lo que no exista es `null`, nunca `""`, `[]` ni `0`.** La excepción: cuando el
  valor no tiene sentido, la lista es `[]`. Una lista vacía significa "la fuente lo tenía
  pero vacío"; `null` significa "no hay dato".
- **Las cadenas se limpian** de espacios redundantes y saltos de línea, y se les quita el
  espacio final. El HTML viene con mucho ruido de plantilla.
- **El HTML se decodifica** antes de texto: `&amp;` debe acabar como `&`, no como
  `&amp;`. Hay títulos reales afectados (por ejemplo `Blue & Malone, detectives imaginarios`).
- **`ceremony_year` se lee, no se calcula**, siempre que se pueda (ADR-009 y ADR-012).
- **Las listas de datos de una película no se ordenan.** Se conserva el orden de la fuente
  y solo se deduplica. La **única** lista que se ordena es `movies`, por título sin
  acentos ni mayúsculas (ADR-013).
- **Se escribe en disco al final**, de forma atómica (fichero temporal y `rename`), para
  que un fallo a mitad no deje `movies.json` corrupto. Hay un test que lo comprueba
  simulando la muerte del proceso.
- **`counts` nunca se escribe a mano.** `save()` lo recalcula siempre a partir de `movies`.
- **Un JSON corrupto lanza `CorruptDocumentError`** en vez de devolver un documento vacío,
  porque empezar de cero destruiría el fichero (ADR-015).
