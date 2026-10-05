# AGENTS.md

Guía práctica para agentes de IA que trabajen en `goya-scraper`.
**No sustituye a `docs/`**: esta solo dice *dónde mirar* y *qué no romper*.
El detalle está en la documentación; aquí no se repite.

---

## 1. Contexto

Scraper educativo que recopila todas las películas nominadas y ganadoras de los Premios
Goya (40 ediciones, 1987–2026) desde `premiosgoya.com`, y las guarda en
`data/movies.json`. Aparte, `data/goya.db` es una proyección SQLite reconstruible.

Dos mitades que **no se mezclan**:

```
http_client ─┐
  parse_*  ──┴─→ model → categories / credited_kinds / persons
                            ↓
                         storage ──→ data/movies.json   (fuente de verdad)
                            └──→ db / import_db / db_validate ──→ data/goya.db
```

`data/movies.json` es la fuente de verdad. `goya.db` se puede borrar y reimportar.
`movies.json` y `cache/` están en `.gitignore` y **no se versionan**.

El proyecto **no tiene Git todavía**. El porqué de cada decisión está en
`docs/decisions.md` (38 ADR), no en un historial de commits. Si algo cambia una
decisión, se escribe un ADR nuevo.

---

## 2. Antes de modificar código

Lee primero el documento de tu tarea. Correspondencia verificada:

| Tarea                                      | Documentación          |
| ------------------------------------------ | ---------------------- |
| Arquitectura, responsabilidades de módulos | `docs/architecture.md` |
| Scraping, recorrido, caché, rate limit     | `docs/scraping.md`     |
| Fuentes y rarezas del HTML                 | `docs/sources.md`      |
| Modelo de datos, campo a campo             | `docs/data-model.md`   |
| Base de datos, esquema, consultas          | `docs/database.md`     |
| Validación y hallazgos                     | `docs/validation.md`   |
| Por qué de cada decisión (ADR)             | `docs/decisions.md`    |
| Entorno, tests, cómo añadir cosas          | `docs/development.md`  |

Antes de tocar nada, comprueba:

1. ¿Existe ya una función o tabla para eso? (`docs/architecture.md` lista los módulos)
2. ¿Hay un ADR que lo decida ya? Si lo contradices, escribe uno nuevo, no lo ignores.
3. ¿El dato **existe en la fuente**? Si no, se escribe un ADR explicando por qué no
   se implementa. Nunca se deriva ni se inventa.
4. ¿Qué test lo cubre? Si no hay test, el cambio no está terminado.
5. Los fixtures de `tests/fixtures/` son HTML real recortado. Si un test falla, **comprueba
   la fixture antes de tocar el código**.

Comandos (usar siempre el venv; el Python del sistema es PEP 668):

```bash
.venv/bin/python -m pytest                    # 394 tests, ninguno toca la red
.venv/bin/python -m goya_scraper              # descarga; ~35 min la 1ª vez
.venv/bin/python -m goya_scraper.import_db    # movies.json -> goya.db
.venv/bin/python -m goya_scraper.db_validate  # compara JSON <-> SQLite
```

No borres `cache/` sin motivo: obliga a repetir las 1719 peticiones.

---

## 3. Reglas importantes

### Integridad de los datos

- **No se inventan datos.** Si un campo no está en la fuente, es `null`.
- **Distingue los tres estados de ausencia**: `null` = "no hay dato", `0`/`[]` = "la fuente
  lo tenía y estaba vacío". Nunca se confunden. Ejemplo: `reported_by_source` es `None`
  si `detail_status != "ok"`; un `0` ahí sería una mentira.
- `reported_by_source.award_categories = None` significa "nunca se registró" (schema v1/v2),
  no "la ficha dice que no ganó nada".
- **El dato crudo se conserva siempre** junto al normalizado: `countries_raw`,
  `category_raw`, `producers_raw`, `nomination_credit.credit_text`. Es lo que hace
  auditable y reversible la normalización.
- **Las erratas de la fuente no se corrigen** (`Fancia`, `Polinia`,
  `Zentropa Entertainments3 ApS`). Corregir el texto de otro es fabricar datos.

### Fuentes y scraping

- **Fuente única**: `premiosgoya.com`. IMDb está prohibida por su `robots.txt`, Filmaffinity
  está tras Cloudflare, Rotten Tomatoes exigiría un matching desproporcionado. Decidido en ADR-004; no lo reviertas sin un ADR nuevo.
- **No se salta protecciones**: ni CAPTCHAs, ni 403, ni 429. Si el sitio bloquea, se para.
- Solo se reintenta error de red y `{500, 502, 503, 504}`. Un 404/403/429 no se reintenta.
- `timeout` siempre. Rate limit de 1.2 s entre peticiones **que salen**.
- **Un fallo individual no para el proceso**, y una edición fallida **no** se anota en
  `editions_scraped`.
- Se guarda `movies.json` **después de cada edición** (ADR-016). No lo muevas al final.
- `parse_edition` y `parse_movie` son funciones puras: reciben HTML, no hacen peticiones.
  Mantenlo para que los tests no necesiten internet.

### Validación

- Tres niveles con significado propio (ADR-019): ERROR = estado imposible / bug;
  AVISO = discrepancia con la fuente; INFO = raro pero legítimo.
- **La validación nunca detiene el proceso** ni repara datos. Señala.
- **Los empates son reales y correctos** (ed. 5, 17, 28, 39). No los "arregles": eso sería
  inventar. Igual con las 3 categorías sin ganador marcado.
- Al comparar etiquetas de categoría, **canonicaliza los dos lados**. La ficha y la
  edición usan el nombre de su año.

### Modelo de datos y base de datos

- Identidad de película = `slug` (ADR-002). El título **nunca** identifica: hay 12 títulos
  en slugs distintos.
- Construye nominaciones con `model.make_nomination()`: canonicaliza y rellena
  `category_raw`.
- `counts` **nunca** se escribe a mano; `storage.save()` lo recalcula. Si cambia la
  estructura del documento, sube `storage.SCHEMA_VERSION`.
- La única lista que se ordena es `movies` (por título sin acentos ni mayúsculas). **Nunca
  uses `locale.strxfrm`**: el orden no sería determinista entre máquinas. Las listas de
  datos de una película conservan el orden de la fuente.
- `credited` significa tres cosas distintas según la categoría (`credited_kinds.py`).
  El importador **se niega** a adivinar una categoría desconocida; no añadas un valor por
  defecto.
- `persons.py` es una decisión humana, no una función. Solo se fusionan grafías **iguales**
  tras normalizar; los parecidos se reportan, no se fusionan.
- En SQLite: `STRICT` en todas las tablas, `PRAGMA foreign_keys = ON` en cada conexión,
  SQL siempre parametrizado (`?`), nunca f-strings. `schema.sql` es la fuente del esquema.
- La importación **reconstruye** la base entera. Tras un fallo queda válida pero **vacía**;
  la recuperación es reimportar.

### Cambios innecesarios

- Módulos planos, sin subpaquetes (ADR-005). Sin ORM, sin CLI en el scraper, sin
  `lxml`, sin Pydantic, sin linter. Cada ausencia está justificada en `docs/architecture.md`.
- **No añadas dependencias, patrones ni abstracciones** sin justificarlas y sin aprobación.
  100 líneas claras antes que 500 de abstracción.
- No "mejores" los datos que son incorrectos en la fuente publica. Se conservan y se documentan.

---

## 4. Errores y aprendizajes

Todo lo que sigue pasó en este proyecto o está fijado por un test que lo fija:

1. **Expectativas inventadas en los tests.** Se colaron `133` minutos en vez de `115`, un
   título mal copiado. **Un valor esperado se lee de la fixture, nunca de la memoria.** Si un
   test falla, comprueba primero la fixture.
2. **Comparar la categoría canónica contra la etiqueta cruda de la ficha** produjo
   conflictos fantasma. Canonicaliza ambos lados antes de comparar
   (`test_validate.py::TestRenamedAwardsAreNotFalseConflicts`).
3. **Un `CHECK` corrupto por bytes de control** (escritura de un fichero largo de una vez)
   creaba el esquema, aceptaba lo bueno y rechazaba lo malo: parecía correcto hasta que
   llegaban datos reales. Por eso los tests de esquema **insertan datos malos de verdad**,
   y uno lee los bytes de `schema.sql` buscando `\x00`.
4. **Tratar un 404 como `error`.** 404 → `not_found`; el resto de fallos HTTP/red → `error`.
   El JSON tiene que distinguirlo.
5. **`award_categories` como `[]` en vez de `None`.** Hace que un dataset viejo parezca
   limpio sin serlo (ADR-023).
6. **Dormir entre peticiones en un acierto de caché** convertía una ejecución cacheada en
   34 minutos de no hacer nada. Hay un test que falla si duerme (ADR-017).
7. **Afirmar que un fallo de importación dejaba intacta la base anterior.** Era falso:
   queda vacía. Corregido en ADR-035, con un test que fija el comportamiento real.
8. **Partir `producers_raw` por comas** rompe el 100 % de los valores con paréntesis. Es
   un string opaco a propósito.
9. **Sobre-separar nombres** produce `["Carmen", "Lola"]` para *Carmen y Lola*. Riesgo
   aceptado: separar de más daña mucho menos que no separar.
10. **`cache_filename` no es inyectivo**: `/a/b` y `/a_b` colisionan. Irrelevante para este
    sitio y documentado; no afirmes lo contrario.
11. **Un informe que solo da números obliga a volver a la web.** Nombrar la categoría en
    disputa es lo que hace útil el validador (ADR-020).
12. **Rutas mal escritas al escribir ficheros.** Verifica siempre la ruta destino antes de
    escribir; el usuario ya paró uno de estos casos.

---

## 5. Workflow

1. **Entender la tarea.** Qué cambia y por qué. Si el dato no existe en la fuente, para y
   escribe un ADR.
2. **Consultar la documentación** de la tabla de la sección 2, y `docs/decisions.md` si
   tocas una decisión existente.
3. **Inspeccionar código y tests** de la zona, más los fixtures reales.
4. **Cambio mínimo.** La fase previa a la nueva: test primero, luego la función pura,
   luego el cableado en `run.py` (`docs/development.md`).
5. **Ejecutar:** `pytest`. Y, si tocaste datos o esquema:
   `import_db` + `db_validate`, más la validación del JSON.
6. **Revisar el resultado:** lee el informe de validación. **0 errores** es el estado
   esperado; los avisos e infos actuales son de la fuente, no nuestros. Un error nuevo es
   un bug introducido por ti.
7. **Documentar** si el cambio lo requiere: actualiza el `docs/` correspondiente y añade un
   ADR si cambia una decisión.

---

## 6. Cambios que requieren especial cuidado

| Zona                      |     | Qué revisar antes de tocar                                                                                                                                   | Dónde                                                       |
| ------------------------- | --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- |
| **Scraping**              |     | ¿Sigue siendo educado? ¿un fallo individual sigue sin parar el proceso? ¿se guarda tras cada edición? ¿sigue sin reintentar 404/403/429?                     | `docs/scraping.md`, `docs/decisions.md` (ADR-010, 016, 017) |
| **Fuentes**               |     | ¿El dato está realmente en la fuente? ¿introduces una fuente externa? ¿cambias un selector porque el HTML cambió?                                            | `docs/sources.md`, ADR-001, 004                             |
| **Modelo de datos**       |     | ¿Subes `SCHEMA_VERSION`? ¿`to_dict()`/`from_dict()` siguen simétricos? ¿conservas el valor crudo?                                                            | `docs/data-model.md`                                        |
| **Base de datos**         |     | ¿Es una tabla nueva justificada por datos medidos? ¿`STRICT`, FK y clave natural siguen()? ¿los ids los sigue asignando el importador en orden determinista? | `docs/database.md`, ADR-025 a 038, `schema.sql`             |
| **Validación**            |     | ¿Es realmente un ERROR o un AVISO? ¿el mensaje nombra el conflicto? ¿la comprobación no repara nada?                                                         | `docs/validation.md`, ADR-019, 020                          |
| **Frontera scraper ↔ BD** |     | El scraper **no** puede importar `sqlite3`. Hay un test (`test_the_scraper_does_not_import_the_database`) que lo falla.                                      | ADR-036                                                     |

---

## 7. Definition of Done

Una tarea está terminada cuando:

- [ ] `.venv/bin/python -m pytest` pasa (394 tests, sin red).
- [ ] Si cambia el JSON: `storage.SCHEMA_VERSION` subido y `docs/data-model.md` al día.
- [ ] Si cambia el esquema: `schema.sql` actualizado, `DB_SCHEMA_VERSION` subido,
  `import_db` + `db_validate` con **0 errores** y `database.md` cambiado.
- [ ] La validación del JSON no ha ganado ningún error nuevo (0 errores; los avisos actuales están
  documentados en `docs/validation.md`).
- [ ] Hay un test que falla si el cambio se deshace.
- [ ] Ningún fichero fuera del proyecto ha sido tocado.
- [ ] Las cifras que aparezcan en `README.md` o `docs/` se han actualizado si han cambiado.
