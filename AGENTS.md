# AGENTS.md

Instrucciones para agentes de IA que trabajen en `goya-scraper`.

Este fichero define cómo trabajar en el proyecto, qué restricciones respetar y cómo verificar los cambios. No sustituye a la documentación técnica: indica qué consultar y cuándo actualizarla.

---

## 1. Contexto y fuentes de verdad

`goya-scraper` recopila información sobre las películas nominadas y ganadoras de los Premios
Goya desde `premiosgoya.com`.

El proyecto tiene dos componentes independientes:

- **Scraper:** obtiene y normaliza los datos y los guarda en `data/movies.json`.
- **Base de datos:** importa ese JSON a SQLite para facilitar las consultas.

`data/movies.json` es la fuente de verdad. `data/goya.db` es una proyección reconstruible. El scraper no debe depender de SQLite.

Consulta los siguientes documentos según la tarea:

| Necesidad                                         | Documento              |
| ------------------------------------------------- | ---------------------- |
| Arquitectura y responsabilidades de los módulos   | `docs/architecture.md` |
| Descarga, caché, reintentos e incrementalidad     | `docs/scraping.md`     |
| Fuentes y particularidades del HTML               | `docs/sources.md`      |
| Modelo JSON y significado de sus campos           | `docs/data-model.md`   |
| Esquema, relaciones y consultas SQLite            | `docs/database.md`     |
| Reglas de validación y anomalías conocidas        | `docs/validation.md`   |
| Decisiones de diseño y alternativas descartadas   | `docs/decisions.md`    |
| Instalación, tests y procedimientos de desarrollo | `docs/development.md`  |

**Jerarquía de referencia:**

1. Las especificaciones vigentes definen el comportamiento que se pretende conseguir en el cambio.
2. El código y los tests existentes permiten establecer el comportamiento implementado actualmente.
3. Los documentos técnicos describen el sistema y sus contratos conocidos.
4. Los ADR explican las decisiones, sus motivos y su evolución.
5. `AGENTS.md` establece las reglas generales de trabajo.

Si encuentras contradicciones, no elijas una interpretación silenciosamente. Identifica las fuentes en conflicto, inspecciona la implementación y los tests, y resuelve la discrepancia antes de diseñar el cambio. Si no puedes determinar la regla correcta, solicita aclaración.

### Estado en Git

El proyecto usa Git sobre la rama `main`, con `LICENSE` MIT.

**Se versiona:** `src/`, `tests/` con sus fixtures, `docs/`, `LICENSE`, `AGENTS.md` y
`data/movies.json`.

**No se versiona:** `cache/` (el HTML crudo, que se vuelve a pedir al sitio),
`data/goya.db` (se reconstruye con `import_db`), `.venv/` y `build/`.

Dos reglas que no se deducen del código:

- **Regenerar el dataset produce un diff enorme.** `data/movies.json` está versionado a
  propósito, para poder consultar los datos sin esperar la descarga. Si vuelves a
  ejecutar el scraper, ese fichero cambia entero: el diff debe ir en un commit propio y
  deliberado, nunca mezclado con un refactor o una corrección, porque si no acaba
  tapando el cambio que sí importa.
- **No borres `cache/` sin motivo.** Es lo que evita tener que volver a pedirle todas las
  páginas al servidor en la siguiente ejecución.

---

## 2. Invariantes del proyecto

Estas reglas deben preservarse salvo que una tarea proponga explícitamente cambiar alguna de ellas y se apruebe la correspondiente decisión.

### Integridad y procedencia de los datos

- La identidad de una película es su `slug`, no su título
- **No se inventan datos.** Si un campo no está en la fuente, es `null`.
- **Distingue los estados de ausencia**: `null` = "no hay dato", `0`/`[]` = "la fuente
  lo tenía y estaba vacío". Nunca se confunden.
- **El dato crudo se conserva siempre** junto al normalizado: `countries_raw`,
  `category_raw`, `producers_raw` son ejemplos de datos crudos. Esto hace
  auditable y reversible la normalización.
- **Las erratas de la fuente no se corrigen** (`Fancia`, `Polinia`,
  `Zentropa Entertainments3 ApS`). Corregir el texto de otro es fabricar datos.

### Scraping y comportamiento HTTP

- **Fuente única**: `premiosgoya.com`. No añadas fuentes externas sin evaluar y documentar la decisión
- **Respeta** el `robots.txt`, el `User-Agent`, los tiempos de espera y el límite de frecuencia existente
- No intentes eludir CAPTCHAs, Cloudflare, HTTP 403, HTTP 429 ni otras protecciones
- Conserva la política de reintentos definida por el proyecto. Antes de modificarla consulta `docs/scraping.md` y los ADR vigentes.
- **Un fallo individual no para el proceso** de las demás películas o ediciones.
- Guarda `data/movies.json` después de cada edición completada; no pospongas toda la persistencia al final del proceso.
- Una edición fallida no debe añadirse a `editions_scraped`; una edición completada sí.
- Conserva estas reglas de recuperación incremental salvo que una modificación aprobada cambie explícitamente su comportamiento.
- Verifica el comportamiento real en el código y los tests antes de cambiarlo.
- `parse_edition` y `parse_movie` son funciones de parseo independientes de la red.

### Modelo y normalización

- Construye nominaciones utilizando las funciones y reglas existentes en `model.py`.
- No escribas manualmente valores derivados que el almacenamiento ya calcula, como los contadores gestionados por `storage.save()`.
- No alteres el orden de los datos sin una necesidad explícita. Mantén el orden determinista definido por el proyecto.
- No inventes un tipo de crédito por defecto para categorías desconocidas. Revisa `credited_kinds.py` y los tests relacionados.
- `persons.py` es una decisión humana, no una función. Solo se fusionan grafías **iguales**
  tras normalizar; los parecidos se reportan, no se fusionan.

### SQLite

- `src/goya_scraper/schema.sql` es la fuente de verdad del esquema SQL.
- Mantén las restricciones de integridad, las claves foráneas y el modo `STRICT` establecido.
- Activa las claves foráneas en cada conexión, como exige el diseño actual.
- Utiliza consultas parametrizadas; no interpolaciones de valores en SQL.
- Conserva la reproducibilidad y el orden determinista de la importación.
- Si cambia el esquema, revisa `DB_SCHEMA_VERSION`, los tests, `docs/database.md` y la validación cruzada con el JSON.
- No afirmes que la base anterior queda intacta si falla la importación. Consulta y respeta la semántica de recuperación documentada.

---

## 3. Tests, fixtures y datos de prueba

Los tests deben ser reproducibles y no depender de Internet.

- Ejecuta los tests desde el entorno virtual del proyecto.
- Utiliza `tests/fixtures/` para representar HTML real y reproducir las particularidades de la fuente.
- Antes de cambiar un parser por un fallo de test, inspecciona la fixture y determina si el error está en el código, en el test o en el HTML de referencia.
- No inventes valores esperados de memoria. Obténlos de las fixtures o de una fuente verificable.
- Cuando cambie la estructura HTML, actualiza la fixture de forma controlada y conserva únicamente el fragmento necesario para reproducir el caso.
- Usa `tmp_path` u otros mecanismos de aislamiento existentes para que los tests no sobrescriban los datos reales.
- En SQLite, comprueba el comportamiento de las restricciones insertando datos válidos e inválidos; contar tablas o inspeccionar nombres no basta.
- Para nuevas reglas de normalización, prueba tanto los casos que deben transformarse como los que deben conservarse sin cambios.
- No elimines un test únicamente porque falle tras la implementación. Determina primero qué comportamiento debe considerarse correcto.

---

## 4. Workflow

1. **Entender la tarea.** Qué cambia y por qué. Si el dato no existe en la fuente, para y
   escribe un ADR.
2. **Consultar la documentación** de la tabla de la sección 1, y `docs/decisions.md` si
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

Comandos, desde la raíz del proyecto:

```bash
.venv/bin/python -m pytest                    # seguro: sin red
.venv/bin/python -m goya_scraper.import_db    # seguro: lee el JSON local
.venv/bin/python -m goya_scraper.db_validate  # seguro: solo lee
.venv/bin/python -m goya_scraper              # LEE ANTES DE EJECUTAR
```

El primero es el que se usa casi siempre. **El cuarto no tiene equivalente a "probarlo
rápido"**: recorre el sitio entero, genera muchísimas peticiones y tarda bastante. Solo
cuando la tarea sea deliberadamente actualizar los datos, nunca para comprobar un cambio
de código. Todo lo que no esté en caché hay que volver a pedirlo al servidor, así que
aguanta hasta que termine en lugar de interrumpirlo.

---

## 5. Cambios que requieren especial cuidado

| Zona | Qué revisar antes de tocar | Dónde consultar |
|---|---|---|
| **HTTP o caché** | Reintentos, timeout, rate limit, recuperación e incrementalidad | `docs/scraping.md`, ADR-010, 016, 017 |
| **Fuentes** | ¿El dato está realmente en la fuente? ¿introduces una fuente externa? ¿cambias un selector porque el HTML cambió? | `docs/sources.md`, ADR-001, 004 |
| **Modelo de datos** | ¿Subes `SCHEMA_VERSION`? ¿`to_dict()`/`from_dict()` siguen simétricos? ¿conservas el valor crudo? | `docs/data-model.md` |
| **Base de datos** | ¿Es una tabla nueva justificada por datos medidos? ¿`STRICT`, FK y clave natural siguen? ¿los ids los sigue asignando el importador en orden determinista? | `docs/database.md`, ADR-025 a 038, `schema.sql` |
| **Validación** | ¿Es realmente un ERROR o un AVISO? ¿el mensaje nombra el conflicto? ¿la comprobación no repara nada? | `docs/validation.md`, ADR-019, 020 |
| **Frontera scraper ↔ BD** | El scraper **no** puede importar `sqlite3` | ADR-036 y el test `test_the_scraper_does_not_import_the_database` |

Si una modificación afecta a varias capas, la especificación debe enumerarlas y establecer las comprobaciones correspondientes.

---

## 6. Documentación y decisiones

Mantén cada documento dentro de su responsabilidad:

- `README.md`: propósito, instalación, uso y navegación.
- `AGENTS.md`: reglas de trabajo, invariantes y proceso para agentes de IA.
- `docs/`: descripción técnica del comportamiento implementado y sus contratos.
- `docs/decisions.md`: motivos de las decisiones relevantes y alternativas consideradas.

Actualiza los documentos existentes en vez de duplicar su contenido en otros ficheros.

Un ADR nuevo está justificado cuando cambia una decisión arquitectónica o de dominio relevante, no por cada cambio de código. Cuando una decisión sustituya a otra, conserva la historia e indica claramente cuál queda vigente.

No mantengas en `AGENTS.md` cifras de estado, listas exhaustivas de anomalías ni narraciones detalladas de incidentes. Ese contenido pertenece al informe de validación o a la documentación de desarrollo. Los *procedimientos* —qué comprobar, cuándo y contra qué— sí pertenecen aquí: no son estado, y un agente no puede deducirlos por sí solo.

---

## 7. Definition of Done

Una tarea está terminada cuando:

- [ ] Las pruebas pasan y los resultados se han comprobado
- [ ] La implementación satisface los criterios de aceptación
- [ ] No se han introducido regresiones ni errores de validación
- [ ] Los invariantes siguen cumpliéndose o se ha aprobado explícitamente su modificación
- [ ] Los documentos técnicos afectados están actualizados.
- [ ] Las decisiones arquitectónicas modificadas están documentadas.
- [ ] El cambio se mantiene dentro del alcance acordado
- [ ] Las pruebas o verificaciones pendientes, limitaciones y riesgos se declaran explícitamente.

Y, cuando el cambio toque el dato o el esquema, estos cuatro:

- [ ] Si cambia la estructura del documento JSON, `SCHEMA_VERSION` está subido.
- [ ] Si cambia el esquema SQL, `DB_SCHEMA_VERSION` está subido.
- [ ] `import_db` y `db_validate` terminan con cero errores.
- [ ] La validación del JSON no ha ganado ningún error nuevo.

Si alguna comprobación no puede ejecutarse, indica cuál, por qué y qué evidencia queda pendiente. No afirmes que una prueba ha pasado si no se ha ejecutado.

---

## 8. Estilo de implementación

- Nombres de código y docstrings en inglés; documentación explicativa en español.
- Funciones pequeñas y responsabilidades claras.
- Comentarios para explicar decisiones o motivos no evidentes, no para repetir el código.
- Dependencias y abstracciones mínimas.
- Sin ORM, CLI adicional, linter ni nuevas dependencias salvo que una tarea aprobada justifique el cambio.

Ante varias soluciones correctas, elige la que preserve mejor la arquitectura existente, sea más fácil de verificar y requiera menos complejidad accidental.
