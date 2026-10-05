# Validación de datos

Cómo se comprueba que `data/movies.json` es coherente, y qué se ha encontrado.

---

## Qué se valida

El programa valida el documento **después de escribirlo**, en cada ejecución. No hay que
recordar lanzar nada: si el dataset cambia, el informe cambia en la misma corrida.

La validación nunca detiene el proceso. Los datos valen aunque tengan errores; lo que hace
falta es señalarlos, no impedir que se guarden.

---

## Tres niveles, y por qué

Lo más importante de este módulo no es qué comprueba, sino **cómo clasifica** lo que
encuentra (ADR-019).

| Nivel | Significado | Ejemplo |
|---|---|---|
| **ERROR** | Estado imposible. Señala a **un bug** (nuestro o del fichero). | Una película con 3 premios y 0 nominaciones |
| **AVISO** | Nuestra cifra y la de la web **se contradicen**. Señala a la **fuente**. | La ficha dice 7 premios, la edición marca 6 |
| **INFO** | Raro pero **legítimo**. No es un problema. | Un empate con 3 ganadoras |

El motivo de esta separación es concreto: **los empates son reales y correctos.** Si el
validador los marcara como error, alguien "los arreglaría" — y arreglar un empate real es
justo lo que este proyecto no hace nunca.

Y lo mismo con las discrepancias: las 4050 nominaciones cuadran **1678/1678**. Las 6
discrepancias de premios son de la fuente, no nuestras. Reportarlas como error sería
señalar hacia el lado equivocado.

Los errores se imprimen primero, así que si algo está roto se ve sin desplazarse.

---

## Comprobaciones

### ERROR — estados imposibles

| `check` | Qué detecta |
|---|---|
| `awards_exceed_nominations` | Más premios que nominaciones. El caso del enunciado. |
| `nomination_total_mismatch` | `total_nominations` no cuadra con la longitud de la lista |
| `award_total_mismatch` | `total_awards` no cuadra con los `won: true` |
| `editions_mismatch` | `goya.editions` no cuadra con las ediciones de las nominaciones |
| `duplicate_slug` | Dos registros con el mismo `slug` |
| `missing_slug` | Un registro sin identificador |
| `films_without_nominations` | Una película sin ninguna nominación |
| `no_editions` | No se registró ninguna edición |
| `counts_disagree` | `_meta.counts` no cuadra con los datos (fichero editado a mano) |

### AVISO — desacuerdo con la fuente

| `check` | Qué detecta |
|---|---|
| `nominations_disagree_with_source` | Our count ≠ el contador de la web |
| `awards_disagree_with_source` | Our count ≠ el contador de la web |
| `award_claimed_only_by_movie_page` | La ficha se atribuye un premio que **ninguna** edición concede |
| `award_claimed_only_by_edition_page` | La edición concede un premio que la **ficha** no cuenta |
| `no_detail_page` | La película existe pero su ficha no se pudo leer |

Los dos últimos son los que hacen útil el validador. No dicen "los números no cuadran",
dicen **qué premio concreto** está en disputa (ADR-020).

### INFO — raro pero legítimo

| `check` | Qué detecta |
|---|---|
| `tied_categories` | Categorías con más de un ganador (empates) |
| `films_in_several_editions` | Una película nominada en dos ediciones |

---

## Resultado sobre los datos reales

```
40 ediciones · 1678 películas · 4050 nominaciones · 1027 premios · 31 categorías
problemas: 0 errores, 12 avisos, 2 informational
```

**0 errores.** El dataset es internamente coherente.

### Cobertura de datos

| Campo | Presente | |
|---|---|---|
| `title` | 1678/1678 | 100% |
| `synopsis` | 1674/1678 | 99% |
| `directors` | 1674/1678 | 99% |
| `countries` | 1623/1678 | 96% |
| `producers_raw` | 1437/1678 | 85% |
| `screenwriters` | 1329/1678 | 79% |
| `cast` | 1130/1678 | 67% |
| `title_original` | 1019/1678 | 60% |
| `duration_minutes` | 522/1678 | 31% |

Las cifras cuadran con lo medido en la exploración (ADR-012). `duration_minutes` al 31% es
un dato de la fuente, no un fallo del scraper: la Academia solo rellena ese campo en parte
de las fichas.

### Los 12 avisos, explicados

Son 6 películas, y cada una genera dos avisos: uno por la cifra y otro por la categoría
concreta. **Ninguna es un error nuestro.**

Que el informe pueda nombrar la categoría concreta es lo que hace útil el aviso: no dice
"aquí hay un problema", dice "la ficha se atribuye 'Mejor actor revelación' pero no hay
ganador marcado". Eso se localiza dentro del JSON, sin volver a la web.

**Grupo A — la ficha se atribuye un premio que la edición no concede (3):**

| Película | Premio que la ficha se atribuye |
|---|---|
| *La niña de tus ojos* | Mejor actor revelación (ed. 13) |
| *La comunidad* | Mejores efectos especiales (ed. 15) |
| *El secreto de sus ojos* | Mejor película hispanoamericana (ed. 24) |

Y aquí está el hallazgo: **esas tres categorías son exactamente las tres únicas de las 40
ediciones que no tienen ganador marcado.** 4 nominados, 0 ganadores, en cada caso.

Es decir: la Academia no marcó al ganador en la página de edición, pero luego escribió el
premio en la ficha de una película. La web se contradice consigo misma.

**Grupo B — la edición concede un premio que la ficha niega (2):**

*El rey de la granja* y *Puerta del tiempo* están marcadas como ganadoras de "Mejor
película de animación" en la edición 17, pero sus fichas no tienen sección de premios: declaran
cero. Y es porque esa categoría tuvo un **triple empate** con *Dragon Hill*. Actualizaron la
ficha de una y olvidaron las otras dos.

**Grupo C — la edición concede un premio que la ficha se salta (1):**

*La gran familia española* tiene marcada "Mejor película" en la edición 28, pero su ficha
solo lista 2 premios. Esa edición tuvo empate a dos con *Vivir es fácil con los ojos
cerrados*.

### Los 4 empates

| Edición | Categoría | Ganadoras |
|---|---|---|
| 5 | Mejor cortometraje | 2 |
| 17 | Mejor película de animación | **3** |
| 28 | Mejor película | 2 |
| 39 | Mejor película | 2 |

Informativos a propósito. El modelo los soporta sin tocar nada.

---

## Por qué el informe nombra la categoría y no solo el número

Con solo contadores, el informe decía: *"la-nina-de-tus-ojos: nosotros 6, la web 7"*. Eso
obliga a volver a la web a averiguar qué pasa.

Con `award_categories` (ADR-020), dice: *"la ficha se atribuye ['Mejor actor revelación'] pero
no hay ganador marcado en la página de la edición"*. Localizado en el propio JSON, sin
salir de ahí.

---

## Cómo se ejecuta

Al final de cada `python -m goya_scraper`. También se puede lanzar sobre el fichero:

```python
from goya_scraper import storage
from goya_scraper.validate import validate, render

document = storage.load()
print(render(document, validate(document)))
```

Sin red, en milisegundos. Es una función pura sobre el documento.

---

## Cobertura de los tests

27 tests en `tests/test_validate.py`, todos sobre documentos construidos a mano para
provocar cada fallo. Incluyen el caso del enunciado (3 premios con 0 nominaciones), el
triple empate, el `slug` duplicado y los contadores manipulados.