# Registro de decisiones (ADR)

Cada decisión técnica relevante del proyecto, con el contexto y las alternativas que
se descartaron. El objetivo es que dentro de seis meses cualquier persona sepa **por qué** el proyecto es como es.

---

## ADR-001 — Fuente de datos: solo `premiosgoya.com`

**Contexto.** Hacen falta nominaciones (con edición y ganador) y fichas de película.
Hay dos dominios oficiales: `premiosgoya.com` y `academiadecine.com`.

**Opciones consideradas.**

1. `premiosgoya.com` (WordPress, post type `pelicula`).
2. `academiadecine.com` como fuente complementaria.
3. Ambas en paralelo.

**Decisión.** Única fuente: `premiosgoya.com`.

**Motivo.** Es la web de los premios y contiene las dos cosas que necesitamos en el mismo
dominio y con el mismo HTML. `academiadecine.com` es la sede institucional (notas de
prensa, bases,/articles) y no aporta datos de películas. Añadir una segunda fuente implicaría
un *matching* entre dominios, que es justo el problema que queremos evitar.

---

## ADR-002 — La identidad de una película es el `slug` que da el servidor

**Contexto.** El requisito es que cada película aparezca una sola vez. La página de
nominaciones enlaza a cada película con `href="/pelicula/{slug}/"`, y su ficha vive en
esa misma URL.

**Opciones consideradas.**

1. `slug` de la URL como clave primaria.
2. Normalizar el título y usar el título como clave.
3. Matching difuso por similitud de títulos.

**Decisión.** El `slug` es la clave primaria y la deduplicación es un diccionario indexado
por él.

**Motivo.** El servidor ya resolvió el problema de identidad por nosotros. Un `slug` es
estable, único y no ambiguo. La opción 2 tiene colisiones evidentes (`Amor`, `Agora` y
`Bella` son títulos reales de películas distintas) y la opción 3 tiene una tasa de error
inevitable.

Verificado además sobre las 1678 películas: **ninguna aparece en dos ediciones**, así que el
riesgo de fusión errónea es prácticamente nulo.

---

## ADR-003 — No incluir el año de la película

**Contexto.** La ficha de película **no tiene** campo de año ni fecha de estreno. La única
relación con una fecha es que una película se concursa en la edición cuyo año de ceremonia
es `edición + 1986`.

**Opciones consideradas.**

1. `release_year: null`.
2. Derivar `release_year = ceremony_year - 1`.
3. Derivar y marcar el campo como derivado.

**Decisión.** `release_year: null`. No se deriva.

**Motivo.** Es un dato *no encontrado*, y la regla del proyecto es no inventar. Además la
derivación tiene una fuente de error real: una película estrenada a finales de año
compite en la edición siguiente, pero loscortometrajes y los films de Documental
incorporanUC una relación con la fecha deiliate podría shifting; no es una regla
constante y no podemos verificarlo con la fuente disponible.

Descartado también por reversibilidad: si algún día se incorpora el año real, se rellena
el campo sin tocar nada más.

---

## ADR-004 — Sin fuentes externas (IMDb, Rotten Tomatoes, Filmaffinity)

**Contexto.** La ficha oficial no enlaza a ninguna fuente externa y no tiene nota, año,
géneros, presupuesto ni recaudación.

**Opciones consideradas.**

1. Incluir IMDb.
2. Incluir Filmaffinity.
3. Incluir Rotten Tomatoes.
4. Ninguna.

**Decisión.** Ninguna. El campo queda preparado en el modelo pero siempre a `null`.

**Motivo.** Comprobado empíricamente, no por impresión:

| Fuente          | Resultado real medido                                                                                                               |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| IMDb            | `robots.txt` → `User-agent: *` + **`Disallow: /`**. Además responde HTTP 202 con cuerpo vacío (desafío JS).                         |
| Filmaffinity    | HTTP **403** + interstitial "Just a moment..." → **Cloudflare**, protección anti-bot explícita.                                     |
| Rotten Tomatoes | Responde HTML; `robots.txt` no prohíbe `/m/`. Pero exige resolver la URL película a película (matching) y es fuente estadounidense. |

IMDb está **prohibida por `robots.txt`** para agentes genéricos, lo que descarta cualquier
uso disciplinado. Filmaffinity está tras una protección que el proyecto no va a saltar.
RT es la única técnicamente posible, pero el beneficio (una nota) no compensa el coste:
1678 búsquedas, un sistema de matching nuevo y riesgo de bloqueo.

El hueco queda documentado en `docs/sources.md` por si en el futuro se decide otra cosa.

---

## ADR-005 — Módulos planos en `src/goya_scraper/`, sin subpaquetes

**Contexto.** El esquema inicial pedido era `scraper/`, `models/`, `storage/`.

**Opciones consideradas.**

1. Subpaquetes `scraper`, `models`, `storage`.
2. Módulos planos: `http_client.py`, `parse_edition.py`, `parse_movie.py`, `model.py`,
   `storage.py`, `run.py`.
3. Arquitectura por capas con interfaces y dependency injection.

**Decisión.** Opción 2.

**Motivo.** El proyecto entero cabe en unos 400 líneas. Con tres o cuatro módulos, los
`__init__.py` de los subpaquetes serían más largos que los propios módulos, y los imports
empezarían a ocultar el flujo de ejecución. Aplanar deja el recorrido visible en un `ls`.
La opción 3 es desproporcionada para este tamaño.

Criterio para replantearlo: si el proyecto superara unas 1500 líneas, o si apareciera un
segundo formato de salida, la estructura por paquetes empezaría a pagar.

---

## ADR-006 — El ganador se detecta con `img[title^="Ganadora"]`

**Contexto.** Hay que distinguir nominados de ganadores en la página de nominaciones.

**Opciones consideradas.**

1. Clase CSS.
2. Posición en la lista.
3. Atributo `title` de una imagen decorativa.

**Decisión.** `img` cuyo `title` empieza por `"Ganadora"`.

**Motivo.** Es la opción **semántica**: el texto es
`"Ganadora del premio Goya a mejor película"`, o sea que la propia fuente declara el estado
y además repite la categoría. No depende del orden (que en principio no está garantizado)
ni de clases que podrían cambiar en un rediseño. Verificado en las 40 ediciones: 1027
marcas de ganador, coherentes con el recuento por categoría.

---

## ADR-007 — `total_nominations` es el número de filas, no el de categorías distintas

**Contexto.** Una película puede tener **varios nominados en la misma categoría**.
`El buen patrón` tiene 3 nominaciones a "Mejor actor de reparto" (Celso Bugallo, Fernando
Albizu y Manolo Solo) y 20 filas de nominación repartidas en 17 categorías.

**Opciones consideradas.**

1. Contar categorías distintas.
2. Contar filas de nominación.
3. Guardar solo las categorías, sin lista.

**Decisión.** `total_nominations = len(nominations)`, es decir, **filas**.

**Motivo.** Es lo que dice la propia web: la ficha de `El buen patrón` muestra
`<span>20</span> Nominaciones`, y lo he verificado cruzando 52 fichas contra las páginas de
edición: **52/52 coinciden exactamente**. Si contáramos categorías distintas,
inventaríamos un número que contradice a la fuente.

La lista de nominaciones se guarda íntegra, así que no se pierde nada: desde `nominations`
siempre se puede recalcular el número de categorías distintas.

---

## ADR-008 — Los productores se guardan en bruto, sin separar

**Contexto.** El campo `Producción` de la ficha viene como texto plano separado por comas.

**Opciones consideradas.**

1. `split(",")` como con las personas.
2. Guardar la cadena tal cual.

**Decisión.** Guardar la cadena intacta en `credits.producers_raw`.

**Motivo.** Los nombres de empresa **contienen comas ellos mismos**. Casos reales
encontrados:

- `"Alba Sotorra, S.L."` → se rompería en 3 trozos
- `"La Claqueta P.C., Bella Animación La Película AIE, Filmgate Miami"` → partly OK
- `"Acció(Acció, Euroview, Digital Dreams, TVC, Mes Films), Televisió de Catalunya, S.A."` → basura
- `"Laurenfilms, S.A. Creativos Asociados De Radio y Televisión S.A. Flamenco Films, S.A."` → basura

Un `split(",")` produciría datos falsos. No podemos partirlo de forma fiable sin un
diccionario de nombres de empresa, que no tenemos. Preferimos un dato en bruto honesto a
una lista inventada. El sufijo `_raw` documenta la ausencia de parseo.

En cambio, `Dirección`, `Guion` e `Intérpretes` **sí** se separan, porque sus valores son
nombres de personas y no contienen comas internas.

---

## ADR-009 — Las categorías se guardan sin normalizar

**Contexto.** Hay **33 nombres de categoría distintos** en 40 ediciones, y muchos son la
misma categoría con otro nombre:

- `"Mejor guion"` (2 ediciones) → `"Mejor guion original"` / `"Mejor guion adaptado"`
- `"Mejor dirección artística"` (36 ediciones) → `"Mejor dirección de arte"` (4 ediciones)
- `"Mejor cortometraje"` (5 ediciones) → se dividió en ficción / animación / documental

**Opciones consideradas.**

1. Guardar el texto original.
2. Unificar automáticamente a un catálogo canónico.
3. Guardar el texto original y añadir un mapeo curado a mano.

**Decisión.** Opción 1 ahora. La opción 3 queda planteada para la Fase 6.

**Motivo.** La unificación automática por similitud de texto sería frágil y podría fusionar
categorías que hoy son distintas a propósito. Un mapeo curado a mano es fiable, pero son 33
entradas que mantener, y es un trabajo de datos, no de software. Empezamos conservando la
etiqueta literal: **no se pierde nada** y es reversible.

---

## ADR-010 — La cache en disco *es* el mecanismo de incrementalidad

**Contexto.** Queremos no repetir descargas. La primera opción sería revalidación HTTP
condicional (`ETag` / `If-Modified-Since`).

**Opciones consideradas.**

1. `ETag` / `Last-Modified`.
2. Registro de "qué se ha descargado" en un JSON aparte.
3. Cache de HTML en disco (`cache/`).

**Decisión.** Opción 3, más un contador de ediciones en la cabecera de `movies.json`.

**Motivo.** **Comprobé que la opción 1 es imposible**: el servidor no envía ni `ETag` ni
`Last-Modified` ni `Cache-Control`. No hay nada contra lo que revalidar.

Entre 2 y 3, la 3 es más simple: el sistema de ficheros *es* el registro. Si el fichero
`cache/edicion_36.html` existe, no hay petición. Y el bonus es grande: **la segunda
ejecución hace cero peticiones**, y los tests de parsing pueden leer HTML real desde la
cache sin tocar la red.

Refresco manual con `rm -rf cache/`.

---

## ADR-011 — `html.parser` de la stdlib en vez de `lxml`

**Contexto.** BeautifulSoup necesita un parser. `lxml` está instalado en el sistema.

**Opciones consideradas.**

1. `lxml` (más rápido y tolerante).
2. `html.parser` de la librería estándar.

**Decisión.** `html.parser`.

**Motivo.** El HTML del sitio es limpio y bien formado; `lxml` no aporta nada aquí. Usar la
stdlib significa **una dependencia menos** que instalar y una menos que documentar.
`lxml` compila desde código C, lo que además complica la instalación en algunos sistemas.
Si el parsing se volviese lento (no lo es: 4050 filas en 40 páginas) es el momento de
reconsiderarlo.

---

## ADR-012 — Dos fuentes de datos, cada una para lo que sabe

**Contexto.** La página de edición y la ficha de película contienen información solapada.

**Opciones consideradas.**

1. Solo páginas de edición (o solo `por-categoria`).
2. Solo fichas de película.
3. Las dos, cada una para lo que sabe, y usarlas como validación cruzada.

**Decisión.** Opción 3.

- **Página de edición**: única fuente de `edition` y del desglose por categoría con ganador.
  De ahí sale la lista de nominaciones.
- **Ficha de película**: única fuente de metadatos (país, dirección, guion, sinopsis,
   …). Además declara sus propios contadores (`N Nominaciones`, `N Goyas`), que sirven de
  **contraprueba** en la Fase 6.

**Motivo.** Pedir 1678 fichas solo para tener nominaciones, o 40 páginas y quedarse sin
sinopsis, sería tirar datos disponibles. Y como los contadores de la ficha coinciden
exactamente con lo que dicen las páginas de edición, la redundancia es **gratis**: es un
control de calidad integrado.

**Ojo con `/premios/por-categoria/`:** esa URL parece el listado completo pero contiene
**solo los ganadores**, uno por categoría. No usarla.

---

## ADR-013 — El JSON lleva un envoltorio `_meta` y las películas van ordenadas

**Contexto.** El requisito era un `data/movies.json` legible por personas. Con 1678
películas, el orden en que se scraping se decide a mucho.

**Opciones consideradas.**

1. Lista pelada: `[ {...}, {...} ]`.
2. Objeto con `_meta` y `movies`.
3. Objeto con `_meta`, y las películas ordenadas por título.

**Decisión.** Opción 3.

**Motivo.** El envoltorio guarda lo que no cabe en una película: qué ediciones se han
procesado (base de la incrementalidad, ADR-010), qué versión del esquema es el fichero, y
los recuentos. Sin él, esa información tendría que ir en otro fichero y habría que
mantener dos cosas sincronizadas.

Sobre el orden: **no** usamos `locale.strxfrm`, porque da resultados distintos según la
máquina y un dataset que se reordena entre ejecuciones es imposible de comparar con
`git diff`. Usamos una clave propia: minúsculas, sin acentos, y desempate por el título
exacto. Determinista en cualquier sistema.

Las películas sin título van **al final**, para que lo que esté roto se vea de un vistazo.

Y con una regla explícita: **las listas de datos de una película no se ordenan.** Se conserva el
orden de la fuente y solo se deduplica. Solo se ordena la lista de películas, porque es la
que se lee de principio a fin.

---

## ADR-014 — Una película sin ficha se conserva, con `detail_status`

**Contexto.** Puede pasar que la página de una película no se pueda leer: 404, error de
red, HTML inesperado. Ese requisito era explícito: *continuar después de que falle una
película*.

**Opciones consideradas.**

1. Descartarla y solo registrar un warning.
2. Conservarla con lo que sabemos: su slug y sus nominaciones, más un estado.

**Decisión.** Opción 2.

**Motivo.** La nominación **sí** la tenemos: viene de la página de la edición, que es otra
página distinta. Descartar la película tiraría datos buenos por un fallo de red. Perder
20 nominaciones por un `timeout` es peor que tener una entrada sin título.

Para que no se confunda, el estado va explícito:

| `detail_status` | Significado                                                      |
| --------------- | ---------------------------------------------------------------- |
| `ok`            | Leímos la ficha                                                  |
| `not_found`     | El servidor dice que no existe (404) o la página no es una ficha |
| `error`         | No pudimos leerla (red, 5xx)                                     |

Y `reported_by_source` es **`null`** cuando el estado no es `ok`. Es un detalle que
importa: con el valor `0` un fallo de red parecería "la web dice que esa película no tiene
ni una nominación", que es mentira. Es exactamente el requisito de distinguir *no
encontrado* de *error al obtener el dato*.

---

## ADR-015 — Un JSON corrupto lanza excepción en vez de empezar de cero

**Contexto.** `load()` lee `data/movies.json`. ¿Qué hacer si está corrupto?

**Opciones consideradas.**

1. Registrar un warning y devolver un documento vacío.
2. Lanzar una excepción y no tocar el fichero.

**Decisión.** Opción 2.

**Motivo.** Si `load()` devolviera vacío, el `save()` siguiente **destruiría** un fichero
que puede haber editado una persona a mano. Perder datos silenciosos es el peor fallo que
puede tener una herramienta de datos. El mensaje de error dice qué hacer.
---

## ADR-016 — Se guarda `movies.json` después de cada edición

**Contexto.** El diseño inicial escribía el fichero una vez, al final de la ejecución.

**Opciones consideradas.**

1. Guardar solo al terminar.
2. Guardar después de cada edición.

**Decisión.** Opción 2.

**Motivo.** Salió de ver el recorrido en marcha, no de pensarlo antes. La primera
ejecución completa se cortó a los 5 minutos por un `timeout` mío, yendo por la edición 10
de 40. Con la opción 1, esos cinco minutos se perdían enteros.

Son ~40 escrituras de unos pocos MB: nada comparado con perder media hora de peticiones ya
hechas. Y la escritura es atómica, así que un corte a mitad de escritura no deja el
fichero corrupto.

Relacionado: **una edición que falla no se anota** en `editions_scraped`. Así la
siguiente ejecución la reintenta sola, sin intervención manual.

---

## ADR-017 — Un acierto de caché no espera entre peticiones

**Contexto.** El diseño decía "siempre `sleep` entre peticiones, también al servir desde
caché".

**Opciones consideradas.**

1. Mantener la pausa también en los aciertos de caché.
2. Solo pausar cuando la petición sale de verdad.

**Decisión.** Opción 2.

**Motivo.** La versión 1 era un error de razonamiento, mío. Servir desde disco **no
toca el servidor**, así que no hay nadie a quien ser educado. Y la consecuencia era
prácticamente ruinosa: con 1.2 s por página y 1719 páginas, una segunda ejecución
totalmente cacheada tardaría **34 minutos** en no hacer absolutamente nada.

Hay un test que falla si se duerme en un acierto de caché, para que nadie lo "arregle" sin
darse cuenta.

---

## ADR-018 — Fase 5 antes que Fase 4

**Contexto.** El plan era Fase 4 (recorrido completo) y luego Fase 5 (robustez). El
usuario pidió invertir el orden.

**Opciones consideradas.**

1. Recorrer las 40 ediciones primero, añadir robustez después.
2. Añadir robustez primero, luego recorrer.

**Decisión.** Opción 2, y la razón es que el plan original tenía un agujero: **un
recorrido de 35 minutos sin caché ni guardado intermedio no es recuperable.** Un corte de
red a mitad tiraría todo. La robustez no es una capa que se pueda añadir al final; es lo
que hace que el recorrido largo sea aceptable.

Los fases 4 y 5 se solapan bastante, y conviene decirlo: la Fase 5 implementó también el
descubrimiento de ediciones y el merging incremental, porque "detectar nuevas ediciones"
era un requisito de incrementalidad del enunciado, no de la Fase 4. Lo que queda de la
Fase 4 es sobre todo ejecutar y verificar.

---

## ADR-019 — La validación distingue error, aviso e información

**Contexto.** La fuente tiene inconsistencias propias: 3 categorías sin ganador marcado,
4 empates, fichas que se atribuyen premios que la edición no concede. Un validador que
tratara todo por igual tendría que elegir entre avisar de todo o no avisar de nada.

**Opciones consideradas.**

1. Un único nivel de "problema".
2. Excepción para lo imposible, aviso para lo que discrepa de la fuente, info para lo raro pero legítimo.

**Decisión.** Opción 2, con tres niveles con significado explícito:

| Nivel   | Qué significa                                                                      |
| ------- | ---------------------------------------------------------------------------------- |
| `ERROR` | Estado imposible o fichero incoherente. Señala a un bug.                           |
| `AVISO` | Los datos se contradicen: nuestra cifra y la de la web. Señala a la fuente.        |
| `INFO`  | Raro pero legítimo: empates, películas en varias ediciones. **No es un problema.** |

**Motivo.** Los empates son reales y correctos. Marcarlos como error obligaría a
"arreglarlos", y arreglar un empate real es inventar datos. Y las 6 discrepancias con la
web **no son bugs nuestros**: las nominations cuadran en 1678/1678. Confundir "la fuente se
contradice" con "el programa está mal" es exactamente el error que hay que evitar.

Los errores se ordenan primero en el informe, así que si algo está roto se ve sin
desplazarse.

---

## ADR-020 — Guardar qué premios dice la ficha, no solo cuántos

**Contexto.** La contraprueba detectaba 6 películas cuyos premios no cuadran con la ficha, pero
solo decía *cuántos* faltaban. Eso obliga a volver a la web a mirar cada caso.

**Opciones consideradas.**

1. Guardar solo `reported_awards` (un número).
2. Guardar además las categorías que la ficha declara haber ganado.

**Decisión.** Opción 2, en `data_quality.reported_by_source.award_categories`.

**Motivo.** Con la lista, el programa **nombra el conflicto**: "la ficha se atribuye 'Mejor
actor revelación' pero no hay ganador marcado en la página de la edición". Eso es accionable
sin salir del JSON. Con un número, solo sabemos que algo falla y hay que investigarlo a mano.

Coste: una lista más corta que 7 strings por película, y **reconstruir el dataset cuesta
29 segundos, cero peticiones**, porque la caché lo tiene todo. Ese coste lo paga la Fase 5,
que es justo para lo que sirve.

---

## ADR-021 — La validación corre al final de cada ejecución, siempre

**Contexto.** Podría ser un script aparte que se ejecute a mano.

**Opciones consideradas.**

1. Script manual de validación.
2. Integrada en `python -m goya_scraper`.

**Decisión.** Opción 2, al final, después de escribir el fichero.

**Motivo.** Una comprobación que hay que recordar ejecutar se acaba forgetting. Si el
dataset cambia, el informe cambia en la misma ejecución. Y es gratis: validar 1678 películas
son unos milisegundos.

La validación **nunca detiene el proceso**. Los datos valen aunque tengan errores; lo que
hace falta es señalarlos, no impedir que se guarden.

---

## ADR-022 — Catálogo curado de categorías, con la etiqueta original siempre a la vista

**Contexto.** ADR-009 dejó las 33 etiquetas sin normalizar, a la espera de un mapeo curado.
Ese mapeo es el que se ha cerrado aquí.

**Opciones consideradas.**

1. Unificar solo los dos pares donde los datos lo confirman.
2. Reparar además "Mejor guion" y "Mejor cortometraje" entre las categorías actuales.
3. Unificar automáticamente por similitud de texto.

**Decisión.** Opción 1, más un tercer camino: las etiquetas sin equivalente se **conservan
como categorías propias** del catálogo.

| Canónica                             | Etiquetas del sitio                                                                         | Ediciones                       |
| ------------------------------------ | ------------------------------------------------------------------------------------------- | ------------------------------- |
| `Mejor dirección de arte`            | «Mejor dirección artística» (ed. 1-36) + «Mejor dirección de arte» (ed. 37-40)              | contiguas                       |
| `Mejor película iberoamericana`      | «Mejor película hispanoamericana» (ed. 23-24) + «Mejor película iberoamericana» (ed. 25-40) | contiguas                       |
| `Mejor guion` *(sin cambios)*        | ed. 1-2                                                                                     | premio propio de esas ediciones |
| `Mejor cortometraje` *(sin cambios)* | ed. 4-6, 12, 15                                                                             | premio propio de esas ediciones |

Cada nominación lleva **`category`** (canónica) y **`category_raw`** (lo que escribió la
web). El mapeo es reversible y auditable. `schema_version` sube a 3.

**Resultado:** 33 etiquetas brutas → **31 canónicas**.

**Motivo.** Las dos fusiones están justificadas por los datos: las dos etiquetas de un par
**nunca coexisten** en una edición y cubren ediciones **contiguas**. Eso es un renombrado, y
lo verifica un test sobre el dataset real.

Las otras dos no se pueden fusionar, y esa es la parte interesante. Un «Mejor guion» de 1987
podía ser original o adaptado; la web nunca lo dice. Un «Mejor cortometraje» de 1990 podía
ser de ficción, animación o documental; tampoco lo dice. Repartirlos exigiría **inventar** a
cuál de los tres pertenece cada uno, que es justo lo que este proyecto no hace. Se quedan
como nombres propios: es la opción que no pierde información y no afirma nada falso.

La opción 3 (similitud de texto) se descartó porque fusionaría cosas distintas a propósito.
«Mejor película de animación» y «Mejor cortometraje de animación» se parecen mucho y son
premios diferentes.

---

## ADR-023 — Un dataset antiguo declara sus propios límites

**Contexto.** `award_categories` se añadió en el schema v2. Un `movies.json` escrito por
una versión anterior no lo tiene.

**Opciones consideradas.**

1. Tratar la ausencia como lista vacía y no comparar.
2. Avisar de que no se puede comparar.

**Decisión.** Opción 2, y solo cuando la ficha **declara** premios. Si declara cero, no hay
nada que comparar y no se avisa.

**Motivo.** Una lista vacía significa dos cosas muy distintas: "la ficha dice que no ganó
nada" (respuesta real, y puede estar en conflicto con nosotros) o "nunca lo registramos"
(un fichero antiguo). Confundirlas hace que un dataset viejo parezca limpio sin serlo, que es
peor que parecer sucio.

---

## ADR-024 — El validador comprueba que el mapeo siga siendo cierto

**Contexto.** `categories.py` es una afirmación sobre la fuente escrita a mano, y puede
envejecer mal.

**Decisión.** `_check_categories()` verifica, sobre el dataset real, que las etiquetas de
cada par renombrado **no coexisten** y que cubren ediciones **contiguas**. Si un día la
Academia usa las dos a la vez, el programa avisa en vez de confiar en una constante.

La comprobación solo se ejecuta con más de 50 películas: un documento de tres películas no puede
demostrar si dos etiquetas coexisten, así que en los tests 작은 saltaría sin motivo.

---

# Fase SQLite

Las decisiones siguientes convierten el dataset en un modelo relacional. Todas salen de
medir el JSON real, no de un modelo imaginado antes de mirarlo. Los conteos que se citan
son los del dataset de 40 ediciones: 1678 películas, 4050 nominaciones, 1027 premios, 31
categorías.

## ADR-025 — Normalizar hasta 3FN, con una desnormalización deliberada

**Contexto.** El JSON es un documento centrado en la película: la nominación está anidada
dentro de la película y las personas, los países y los premios son cadenas repetidas. Para
preguntar "directores con más Goya" hay que recorrer 1678 objetos en Python.

**Opciones consideradas.**

1. Una tabla gigante con `director1`, `director2`, `casting_completo`, `countries_csv`.
   Una tabla, cero joins, imposible preguntar "todas las películas de Luis Tosar".
2. Normalización agresiva: una tabla por cada cadena, incluidas las
   `synonym`, `note_kind`, `duration_value`, `missing_field`, `issue`, `position`.
3. 3FN pragmático: lo que tiene identidad propia va a tabla; lo que describe a su dueño se
   queda en columna.
4. Esquema en estrella para BI. Necesario con millones de filas; aquí hay 4050.

**Decisión.** Opción 3, con la regla: *si algo tiene identidad propia y se puede
referenciar, va a tabla; si es un literal que describe a su dueño, va a columna.*

**Con una única desnormalización:** `nomination.credit_fingerprint` (ADR-028). No es una
copia de negocio, es una clave, y sin ella no hay restricción `UNIQUE` que vigile la
importación.

**Motivo.** Las 20 consultas de ejemplo funcionan sin tocar una sola tabla extra. La prueba
de que el punto es el correcto: ninguna necesitó algo que no se propusiera.
`producers_raw` sigue siendo columna porque partirlo sería inventar (ADR-033).

**Consecuencia.** `missing_fields` y `issues` no se importan. `missing_fields` está
verificado al 100% como `{campo IS NULL}` de los cuatro campos que rastrea, e `issues` está
vacío en las 1678. Tabla para ellos sería normalizar ruido.

---

## ADR-026 — La película se identifica por `slug`, con id surrogate

**Contexto.** `movie` necesita clave. El JSON ofrece `slug` y `title`.

**Opciones consideradas.**

1. `title` como clave. **Descartada, medido:** doce títulos están en slugs distintos
   (`alma`/`alma-2`, `rome`/`roma-2`, `Campeones`, `Cerdita`, `Cuerdas` tiene tres,
   `Decorado`, `La buena vida`, `La clase`, `Madre`, `Matria`, `Sorda`, `Un día perfecto`).
2. `slug` como PRIMARY KEY. Funciona, pero ata las once tablas al servidor: si el slug
   cambiara, habría que actualizar miles de filas o romper la integridad.
3. `id` surrogate con `slug UNIQUE`.

**Decisión.** `movie(id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, …)`, con el `id`
asignado en orden alfabético de `slug` para que sea determinista.

**Motivo.** El slug es la identidad **del servidor** (ADR-002) y lo único disponible: la
ficha no tiene identificador interno. Pero la clave primaria la pone la base de datos, no
el servidor. Con surrogate, un cambio de slug futuro es un `UPDATE` de una fila y las
2–20 nominaciones de esa película no se enteran.

**Consecuencia.** `url` no se almacena: es `SITE_URL || '/' || slug || '/'`. Una columna
derivable que puede desincronizarse no aporta nada.

---

## ADR-027 — La persona no tiene identificador; su identidad es el alias y las fusiones se curan

**Contexto.** `person` necesita clave y la fuente **no da ningún identificador**: solo
texto. Además hay 90 grupos de grafías que se refieren a la misma persona.

**Opciones consideradas.**

1. `name` como PRIMARY KEY. Imposible: el nombre no es identidad y hay que elegir uno por
   persona.
2. `name_key` calculada (sin acentos, minúsculas, espacios colapsados). **Descartada, y
   está medido por qué.** Fusionaría `Gloria`/`gloria` y `Jamón`/`jamón`, que son
   **fragmentos de títulos** del fallo de `split_people`. Y elegir la grafía por regla
   produce `Jose Coronado` en vez de `José Coronado`.
3. Elegir la grafía **más frecuente**. **Descartada también.** `Iciar Bollain` aparece 34
   veces e `Icíar Bollaín` solo 5, y la primera es la que está mal. `Tina Sáinz` y
   `José Luís Quirós` (una `l` por `ll`) también ganan por frecuencia. Y **25 de los 90
   grupos son empates exactos**: los datos no pueden desempatarlos.
4. `person_alias` con un mapa curado a mano.

**Decisión.** Tabla `person_alias(alias TEXT PRIMARY KEY, person_id)` con 90 grupos
escritos a mano, más `person(name UNIQUE)` con el nombre limpio. 6130 grafías colapsan en
**6033 personas**.

**Motivo.** Tres razones, por orden de peso.

1. **Reversibilidad.** El principio del proyecto es preferir registros separados antes que
   una fusión equivocada. Con `person_alias` se deshace una fusión borrando una fila, y se
   puede siempre preguntar por qué dos nombres son la misma persona.
2. **Idempotencia.** La importación busca por `alias`, el texto exacto del JSON, así que el
   resultado no depende del orden de inserción.
3. **Correctitud.** Está **probado** que cualquier regla automática equivoca la grafía.

**Qué sí es una regla:** *agrupar*. Dos grafías son del mismo grupo solo si son **iguales**
(no parecidas) tras normalizar Unicode, quitar acentos, colapsar espacios e ignorar
guiones y apóstrofos. Eso es una igualdad demostrable, no una conjetura, y el test
`test_every_curated_group_is_reproducible_from_the_data` la recalcula desde los datos para
que la tabla no pueda envejecer en silencio.

**Consecuencia.** 70 grupos saldrían solo con acentos; 21 más aparecen al ignorar guiones
(`Ángeles González- Sinde`, `José Luis López- Linares`). Los ~80 pares **parecidos** que
quedan no se fusionan: `near_duplicates()` los reporta y `NEAR_DUPLICATES_ARE_NOT_MERGED`
documenta siete con motivo, porque `Agustí` y `Agustín` Villaronga son dos personas.

---

## ADR-028 — `nomination` usa id surrogate, y `credit_fingerprint` hace de clave natural vigilada

**Contexto.** La nominación no tiene identidad en el JSON: es una fila anidada. Y
`(movie, edition, category)` **no es única**.

**Opciones consideradas.**

1. `(movie_id, edition_id, category_id)`. **Medido: 46 ternas se repiten de verdad.** En
   *Alcarràs*, edición 37, hay dos nominaciones de Mejor actor revelación, una por cada
   actor. *Belle époque*, edición 7, tiene dos actores de reparto. Rechazaría 46 filas
   reales.
2. `(movie_id, edition_id, category_id, credited)`. `credited` es una **lista**: un
   `UNIQUE` sobre texto concatenado es frágil, y cambiar el separador rompe la
   restricción en silencio.
3. `id` surrogate sin más. Funciona, pero no deja nada que impida una doble importación.
4. `id` surrogate más `credit_fingerprint` con `UNIQUE` compuesto.

**Decisión.** Opción 4.

```sql
credit_fingerprint TEXT NOT NULL
CREATE UNIQUE INDEX nomination_natural_key
    ON nomination (movie_id, edition_id, category_id, credit_fingerprint);
```

- Categoría de persona → `"p:123|p:45"`, con `person_id` y no el nombre, para que corregir
  una grafía no cambie la clave.
- Categoría de obra o canción → `"t:<texto>"`, porque no hay otra cosa.

**Motivo.** Es la clave natural real, expuesta como restricción en lugar de como
convención. Verificado sobre los datos: **4050 filas, cero rechazos**. Los 17 casos de
`(edición, categoría, texto)` repetido son películas distintas y los 46 de terna repetida
tienen créditos distintos, así que ninguno choca.

**Consecuencia.** Una doble importación falla en vez de duplicar 4050 filas. El coste es
una columna desnormalizada y unas seis líneas de cálculo.

---

## ADR-029 — No existe tabla `award`: `won` es una columna

**Contexto.** Ganar parece una entidad, pero en este dataset la nominación *es* el hecho:
la edición 5 "Mejor cortometraje" tiene tres nominaciones y dos son ganadoras.

**Opciones consideradas.**

1. `award(id, nomination_id UNIQUE)`. 1027 filas sombra de una columna booleana, cero
   información nueva.
2. `award(id, category_id, edition_id, movie_id)` con `UNIQUE(category_id, edition_id)`.
   **Rompe con los datos reales:** cuatro ediciones tienen empate (una con tres ganadoras),
   así que la restricción no se puede cumplir.
3. `won INTEGER NOT NULL CHECK (won IN (0,1))` en `nomination`.

**Decisión.** Opción 3. No hay tabla `award`.

**Motivo.** Una tabla aparte solo tendría sentido si un premio tuviera datos propios: fecha
de entrega, coste, aceptación. No los tiene. Y el argumento queda demostrado por la Fase de
consultas: "ganadoras de Mejor película por año" sale **sin `GROUP BY` y sin lógica de
desempate**, y da dos filas en 2014 y 2025 correctamente.

**Consecuencia.** `SUM(won)` sustituye a `COUNT` sobre `award`. `1027 = SUM(won)`.

---

## ADR-030 — `credited_kind` es dato curado, y `nomination_credit` guarda el literal

**Contexto.** `credited` significa **tres cosas distintas** según la categoría: 3922
nombres de persona, 1158 títulos de obra y 197 canciones.

**Opciones consideradas.**

1. `nomination_credit(nomination_id, person_id, movie_id)` polimórfica. El `movie_id`
   **no puede** conectarse. Medido: ocho créditos de categorías de obra coinciden con el
   título de **otra** película, porque *Carmen y Lola* se acreditó como `["Carmen",
   "Lola"]` y existe una película *Carmen*. Enlazar por texto crea uniones **falsas**.
2. Resolver comparando con `movie.title` en tiempo de importación. Frágil, y dependiente
   de limpiar el texto.
3. `category.credited_kind` curado, `credit_text` siempre, `person_id` opcional.

**Decisión.** Opción 3. `category.credited_kind TEXT NOT NULL CHECK (credited_kind IN
('person','work','song'))`, con los 31 valores escritos a mano junto a `categories.py`.

**Motivo.** El modelo **no adivina**: guarda siempre el texto y resuelve solo cuando una
tabla curada lo autoriza. La medición da **cero inconsistencias en 4050 filas**: ninguna
categoría de persona acredita un título y ninguna de obra acredita un nombre.

**Consecuencias.**

- Nada se pierde. La corrupción de `credited` queda guardada y consultable, pero no se
  propaga: la consulta de créditos que no coinciden con el título devuelve 218 filas, y
  ninguna puede convertirse en una unión.
- La categoría `song` reconoce que `"Aquí Sigo - Compositores: Emilio Aragón"` no es ni una
  persona ni una obra. Un modelo con dos polos la habría deformado.
- `credited_kind` habilita consultas que de otro modo no existirían, como la frecuencia por
  categoría mostrando el tipo de cada una.
- `credited_kind` devuelve `None` para una categoría desconocida, y el importador **se
  niega** a importarla en vez de asumir `person`.

**Alternativa descartada:** una tabla `category_alias(raw_name → category_id)`. Habría
dado 33 filas en vez de repetir `category_raw` 4050 veces, pero `category_raw` describe la
fila y no la categoría: la etiqueta depende del año de esa nominación.

---

## ADR-031 — Se almacena lo atómico; se calcula lo derivado

**Contexto.** El JSON guarda once campos que se pueden calcular.

**Decisión.**

| Se almacena                                      | Se calcula                                            |
| ------------------------------------------------ | ----------------------------------------------------- |
| `movie.slug`, títulos, duración, `producers_raw` | `movie.url` a partir de `slug`                        |
| `goya_edition.number` y `ceremony_year`          | `goya.editions` desde `DISTINCT edition_id`           |
| `movie.reported_nominations`, `reported_awards`  | `goya.total_nominations` y `total_awards` (vista)     |
| `nomination.category_raw`                        | `data_quality.missing_fields` desde `{campo IS NULL}` |
| `nomination_credit.credit_text`                  | `data_quality.issues`, siempre vacío                  |

**Motivo.** Una columna derivable es una **segunda verdad** que puede divergir de la
primera sin que nada se entere. `movie_totals` devuelve 4050 y 1027, exactamente lo que
dice `_meta.counts`, verificado.

**La excepción deliberada** es ADR-032.

---

## ADR-032 — Lo que dice la fuente se conserva, aunque también se pueda calcular

**Contexto.** `total_nominations` es derivable y `reported_by_source.nominations` vale lo
mismo en las 1678 películas. ¿Mismo trato?

**Decisión.** No. Se almacenan los dos y se contrastan.

| Campo                         | Qué es                                        |
| ----------------------------- | --------------------------------------------- |
| `nomination.won`              | Lo que **medimos** en la página de la edición |
| `movie.reported_awards`       | Lo que **dice** la ficha de la película       |
| `reported_award.category_raw` | **Qué** premios dice la ficha                 |

**Motivo.** No son el mismo hecho: son **dos fuentes independientes** que hay que poder
comparar. El dataset contiene seis contradicciones, y sin `reported_award` serían
invisibles en SQL.

**Consecuencia.** `reported_award` es tabla y no dos columnas porque
`award_categories` es una lista de 1027 cadenas en 538 películas, con etiquetas **crudas del
año de esa película**. Es la tabla que hace visible el caso de *La niña de tus ojos*: la
web dice `Mejor dirección artística`, la edición concede `Mejor dirección de arte`.

---

## ADR-033 — Tres estados de ausencia, y por qué `producers_raw` no es una tabla

**Contexto.** "No hay dato" tiene tres formas distintas en este proyecto, y confundirlas
es el error más caro posible.

**Decisión.** Los tres estados se distinguen en el esquema:

| Estado                           | Representación   | Ejemplo real                                                                    |
| -------------------------------- | ---------------- | ------------------------------------------------------------------------------- |
| La web no lo registró            | `NULL`           | `reported_awards IS NULL` significa que no leímos la ficha                      |
| La web lo registró y está vacío  | `0` o cero filas | *El rey de la granja*: `reported_awards = 0` y ninguna fila en `reported_award` |
| La web lo registró y sí lo tenía | valor o filas    | *El buen patrón*: 6 en `reported_awards`, 6 filas                               |

Se blinda con `CHECK ((detail_status = 'ok') = (reported_awards IS NOT NULL))`.

**`producers_raw` y `countries_raw` siguen siendo cadenas opacas.** No hay tabla de
productoras.

**Motivo.** Medido: **el 100% de los 297 `producers_raw` con paréntesis se rompen** con un
split por comas, porque las empresas llevan comas dentro y hay personas en el mismo
texto. Una tabla obligaría a inventar 1437 particiones.

**Las erratas de país no se corrigen.** `Fancia`, `Polinia`, `Potugal`, `Extranjera` (que
no es un país) y `México España` (que no se partió) son lo que dijo la fuente. Por eso
`country` tiene id surrogate y `name` es solo una etiqueta. Corregirlas sería una curaduría
posterior y revisable, no un efecto secundario de importar.

---

## ADR-034 — `sqlite3` de la librería estándar, tablas `STRICT`, tipos decididos por el motor

**Contexto.** ¿Qué librería y qué nivel de tipado?

**Opciones consideradas.** SQLAlchemy, peewee o `datasets` son ORMs con capa de
abstracción y migraciones; para 4050 filas y un proyecto educativo son cinco veces la
complejidad para cero ganancia. La alternativa es `sqlite3` con SQL a mano.

**Decisión.**

1. **`sqlite3` de la librería estándar.** El proyecto pasa de dos dependencias
   (`requests`, `beautifulsoup4`) a dos. Ninguna más.
2. **`PRAGMA foreign_keys = ON` en cada conexión.** SQLite la deja **apagada** por
   defecto y es por conexión: una base escrita sin ella puede contener filas huérfanas que
   parecen correctas hasta que alguien pregunta. Hay un test que lo comprueba.
3. **`STRICT` en las trece tablas.** Requiere SQLite 3.37+. Elimina la coerción silenciosa:
   si el importador intenta meter `'105 años'` en `duration_minutes`, falla en vez de
   aceptarlo como texto. Obliga a `INTEGER CHECK (won IN (0,1))` en lugar de un `BOOLEAN`
   que no existe.
4. **Los identificadores los asigna el importador**, en orden determinista. Sin
   `AUTOINCREMENT`, que solo añade `sqlite_sequence`.

**Motivo.** El objetivo declarado es aprender la diferencia entre modelo documental y
relacional. Un ORM esconde justo lo que hay que ver: las claves foráneas, los `JOIN`, los
índices. Y `STRICT` es una palabra clave de SQLite, no una dependencia nueva; quitarla
degrada el esquema sin romperlo.

**Consecuencia.** Todo el SQL va en el código con parámetros `?`. Nunca f-strings.

---

## ADR-035 — La importación reconstruye la base entera dentro de una transacción

**Contexto.** ¿Cómo se importa? El JSON es la fuente de verdad única.

**Opciones consideradas.** Importación incremental con
`INSERT … ON CONFLICT DO UPDATE` y borrado manual de lo que ya no está, que tiene que
detectar **borrados**: una nominación que la Academia retiró de su web. Complejidad real
para beneficio cero, porque el JSON ya está completo.

**Decisión.** `BEGIN IMMEDIATE` y, dentro, borrado del fichero, creación del esquema e
inserción de todo.

**Motivo.**

- **Reproducible**: importar dos veces el mismo JSON da el mismo archivo. Los ids los
  asigna el importador en orden de `slug`, `category` y `edition`.
- **Atómica dentro de sí misma**: un fallo deshace todas las filas de esa ejecución.
- **Sin estado residual**: si una versión del importador cambia una regla, la base se
  reconstruye en vez de quedar mezclada con filas viejas.

**Lo que NO protege, y conviene decir:** el fichero anterior. `create_database` lo borra
antes de escribir, así que tras un fallo queda una base válida pero **vacía**. La
recuperación es reimportar, y por eso todo el proceso es un único comando reproducible.
Una afirmación anterior de que el fallo dejaba intacta la base previa era falsa, y hay un
test que fija el comportamiento real.

**Consecuencia.** `import_run` acumula historial en vez de sobrescribirse, así que la
reproducibilidad es **auditable**. Y `json_sha256` responde "¿esta base salió del JSON que
tengo ahora?".

---

## ADR-036 — `db` cuelga de `storage`, nunca al revés

**Contexto.** La arquitectura pedida: mantener separados *scraping*, *representación*,
*persistencia JSON* y *persistencia SQLite*, y que el scraper no dependa de SQLite.

**Decisión.**

```
http_client ──┐
               ├─→ model → categories → credited_kinds
   parse_* ────┘           │                └→ persons
                           ↓ storage ──→ data/movies.json
                           │
                           └─→ db, import_db, db_validate ──→ data/goya.db
```

| Módulo              | Responsabilidad                                          |
| ------------------- | -------------------------------------------------------- |
| `credited_kinds.py` | Los 31 `credited_kind` curados, junto a `categories.py`  |
| `persons.py`        | Los 90 grupos de fusión de nombres                       |
| `db.py`             | `SCHEMA`, `connect()`, `create_database()`               |
| `import_db.py`      | `import_document()` y `python -m goya_scraper.import_db` |
| `db_validate.py`    | Comprobaciones contra el JSON y informe                  |

**`credited_kinds` y `persons` no importan SQLite**, igual que `categories.py` no importa
nada: son conocimiento curado del dominio, y por eso son reutilizables por el scraper en
el futuro.

**Motivo.** La regla es una sola y es testeable: **`run.py` no debe importar `db`**. El test
correspondiente importa `run` en un subproceso y comprueba que `goya_scraper.db` no está
en `sys.modules`. Si algún día el scraper necesitara la base, ese test fallaría.

**Consecuencia.** Módulos planos, sin subpaquetes, igual que hasta ahora.

---

## ADR-037 — El esquema vive en un fichero `.sql`, y los tests comprueban comportamiento además de estructura

**Contexto.** El esquema son 250 líneas de SQL. ¿Dónde vive?

**Opciones consideradas.** Dentro de Python como constante, o en `schema.sql` aparte.

**Decisión.** `src/goya_scraper/schema.sql`, leído por `db.read_schema()`.

**Motivo.** Se puede inspeccionar con cualquier editor y ejecutar con
`sqlite3 data/goya.db < src/goya_scraper/schema.sql` sin pasar por Python, que es lo que
uno quiere al leer el modelo por primera vez. El fichero además está ordenado para que las
tablas referenciadas vayan primero, así que funciona como script.

**Y una decisión sobre cómo probarlo.** Las comprobaciones estructurales leen
`sqlite_master` y confirman que se creó lo que se quería crear. Pero pasarían igual de
contentas con un `CHECK` mal escrito, porque un `CHECK` dañado **sigue rechazando los
valores que le decimos que rechace**. Por eso los tests que importan son de
comportamiento: insertan datos malos y exigen que la base los rechace.

Eso no es un detalle. Durante esta fase, escribir un fichero largo produjo bytes de control
en varias restricciones. Una tabla con un `CHECK` así habría creado el esquema, aceptado
los 31 valores buenos y rechazado los malos: **parecería correcta hasta que llegaran datos
reales**. Hay un test que lee los bytes del `.sql` y falla si aparece un `\x00`, y hay
tests que insertan una duración de texto, una nominación de película inexistente, un
`credited_kind` inventado y una clave natural duplicada.

---

## ADR-038 — Sin `STRICT` el módulo se niega, en vez de crear un esquema más débil

**Contexto.** `STRICT` necesita SQLite 3.37+. Este proyecto usa 3.45.1, pero la librería
puede cambiar.

**Opciones consideradas.** Crear el esquema igualmente y perder la garantía de tipo, o
comprobar la versión.

**Decisión.** `db.create_database()` comprueba la versión y lanza `DatabaseError`
explicando qué falta.

**Motivo.** Un esquema sin `STRICT` acepta `'105 años'` en una columna de duración y
funciona hasta que alguien consulta. Un error al empezar es más barato que un dato
corrupto tres fases después.
