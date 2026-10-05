# Fuentes de datos

Qué usamos, por qué, y qué **no** usamos.

---

## Fuente única: `premiosgoya.com`

**Base:** `https://www.premiosgoya.com`

**robots.txt:** devuelve **404**. No hay fichero, por tanto no hay restricciones
declaradas. El scraper lo comprueba igualmente en cada ejecución (ADR-010).
**Tecnología:** WordPress con un custom post type `pelicula`.
**Protección anti-bot:** ninguna detectada. Peticiones `requests` normales funcionan.

### Páginas y qué aportan

| URL                          | Qué aporta                                                                                 | Peticiones |
| ---------------------------- | ------------------------------------------------------------------------------------------ | ---------- |
| `/`                          | El índice de ediciones: `/1-edicion/` … `/40-edicion/` con su año.                         | 1          |
| `/{n}-edicion/nominaciones/` | **Nominaciones completas** de la edición: categoría, película, acreditado y ganador.       | 40         |
| `/pelicula/{slug}/`          | **Ficha** de la película: país, dirección, guion, reparto, sinopsis, duración, contadores. | 1678       |
|                              |                                                                                            | **1719**   |

### Páginas que existen pero **no** se usan

| URL                                    | Por qué se descarta                                                                                                                                                                                  |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/{n}-edicion/`                        | Página editorial. **Cero** enlaces a películas. No sirve para descubrir nada.                                                                                                                        |
| `/{n}-edicion/premios/por-categoria/`  | **Trampa.** El nombre sugiere el listado completo, pero contiene **solo los ganadores**, uno por categoría. 28 filas para 28 categorías. Si se usara, obtendríamos 1027 Nominaciones en vez de 4050. |
| `/{n}-edicion/nominaciones/por-letra/` | Las mismas nominaciones agrupadas por película. Es una vista alternative, no aporta datos nuevos.                                                                                                    |
| `/sitemap.xml`, `/wp-sitemap.xml`      | **404.** No hay sitemap, así que no hay forma de descubrir películas sin pasar por las páginas de edición.                                                                                           |
| `academiadecine.com`                   | Sede institucional: notas de prensa, bases, insides. Sin datos de películas (ADR-001).                                                                                                               |

---

## Cómo se identifica a una película

Por el **`slug`**, el identificador que aparece en `href="/pelicula/{slug}/"`. Es una clave
primaria estable y la da el servidor, así que no hace falta ningún tipo de matching
(ADR-002).

Comprobado sobre las 1678 películas: **ninguna aparece en más de una edición**, así que el
riesgo de fusionar dos películas distintas es prácticamente nulo.

---

## Cómo se identifica a un ganador

Por el atributo `title` de una imagen decorativa:

```html
<img title="Ganadora del premio Goya a mejor película" …>
```

Es la opción **semántica** de las tres disponibles (ADR-006). La propia fuente declara el
estado en texto plano y además repite la categoría. No depende del orden de los elementos
ni de clases CSS que podrían cambiar con un rediseño.

El texto empieza siempre por `"Ganadora"`, incluso para categorías como "Mejor actor", así
que un solo prefijo basta.

**Coherencia verificada:** 1027 marcas de ganador en las 40 ediciones.

---

## Rarezas reales del HTML

Encontradas al implementar el prototipo. **No son bugs nuestros**: son datos que la fuente
publica así, y los conservamos tal cual.

| Rareza                                                                   | Ejemplo real                                           | Qué hacemos                                                                                                                |
| ------------------------------------------------------------------------ | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| El título lleva una coma que **no** separa personas                      | `"Libertad, de Clara Roquet"`                          | Se separa igual, dando `["Libertad", "de Clara Roquet"]`. No lo "corregimos": no podemos saber qué quería decir la fuente. |
| En "Mejor canción original" el acreditado es **el título de la canción** | `"Te espera el mar - Compositores: Maria José Llergo"` | Se guarda tal cual. Unificar el formato entre categorías sería inventar.                                                   |
| Erratas en la fuente                                                     | `"Zentropa Entertainments3 ApS"` (falta un espacio)    | Se conservan. Corregir el texto de otro es fabricar datos.                                                                 |
| En "Mejor película" el acreditado es **la propia película**              | `"El buen patrón"`                                     | Se guarda tal cual. Queda documentado para que no se lea como un error.                                                    |
| El contador de premios **desaparece** si es 0                            | —                                                      | `None` se interpreta como **0**, no como "desconocido". Ocurre en 112 de las 173 películas de la muestra.                  |
| `Nacionalidad` usa género gramatical                                     | `"Española"` en vez de `"España"`                      | Se normaliza a `["España"]` y se conserva `countries_raw`.                                                                 |
| `Duración` solo existe en el 30% de las fichas                           | —                                                      | `null` cuando no está.                                                                                                     |
| Productoras con **comas internas**                                       | `"Alba Sotorra, S.L."`                                 | No se separan. `producers_raw` es una cadena (ADR-008).                                                                    |

Sobre el separador de nombres: la fuente usa `,`, ` y ` y ` e `. Separar por ` y ` puede
partir un nombre que lo lleve dentro, y aceptamos ese riesgo a propósito porque separar de
más daña mucho menos que no separar. **Comprobado sobre 559 campos de persona reales: cero
casos problemáticos.**

---

## Fuentes externas: descartadas

Se evaluaron las tres opciones razonables. Los resultados son **medidos**, no suposiciones.

### IMDb — descartada

```
$ curl -s https://www.imdb.com/robots.txt | grep -A2 "^User-agent: \*"
User-agent: *
Disallow: /
```

**El sitio entero está prohibido por `robots.txt` para agentes genéricos.** Además, una
petición directa devuelve **HTTP 202 con cuerpo vacío**, que es un desafío de JavaScript.

No hay forma de usar IMDb de forma disciplinada. Punto.

### Filmaffinity — descartada

```
$ curl -o /dev/null -w "%{http_code}" https://www.filmaffinity.com/es/film550298.html
403
```

La respuesta es un interstitial **"Just a moment..." de Cloudflare**. Es un mecanismo
anti-bot explícito y el proyecto no va a saltarlo.

### Rotten Tomatoes — descartada por coste/beneficio

Es la única técnicamente posible: responde HTML normal y su `robots.txt` no prohíbe `/m/`.
Pero:

- **No hay forma de pasar de una película a su URL.** Habría que resolver 1678 búsquedas
  por título, con todos los problemas de matching que eso implica.
- Es una fuente **estadounidense**: no cubre todo el catálogo.
- El resultado sería **una nota**, que es el único dato que aportaría.

Siendo honesto: no es imposible, es desproporcionado. Si algún día se quisiera, sería un
proyecto aparte, con su propio ADR. La decisión está registrada en ADR-004.

---

## Qué datos no existen en la fuente

Comprobado revisando 173 fichas reales:

| Campo pedido               | ¿Existe?           |
| -------------------------- | ------------------ |
| título                     | Sí, 100%           |
| título original            | Sí, 60%            |
| duración                   | Sí, 30%            |
| país/es                    | Sí, 98%            |
| sinopsis                   | Sí, 99%            |
| director/es                | Sí, 99%            |
| guionistas                 | Sí, 77%            |
| reparto                    | Sí, 73%            |
| productoras                | Sí, 86% (en bruto) |
| **año**                    | **No**             |
| **fecha de estreno**       | **No**             |
| **géneros**                | **No**             |
| **presupuesto**            | **No**             |
| **recaudación**            | **No**             |
| **director de fotografía** | **No** como campo  |
| **compositor / música**    | **No** como campo  |
| **montador**               | **No** como campo  |

### Sobre dirección de fotografía, música y montaje

Es tentador deducirlos: en la página de nominaciones, el acreditado de "Mejor dirección de
fotografía" de una película **es** su director de fotografía. Pero eso sería **afirmar una
relación que la fuente no afirma**: en una categoría con tres nominados, la web muestra a
los nominados, no al equipo técnico completo de la película. Puede que esa persona no sea
la responsable de fotografía de toda la película.

No lo hacemos. Preferimos `null` a un dato que parece bueno y no lo es. Si algún día se
quiere, es una decisión de datos que debe documentarse aparte.

---

## Perfilado del servidor

Medido durante la exploración:

| Aspecto                      | Valor                                                          |
| ---------------------------- | -------------------------------------------------------------- |
| Tiempo de respuesta          | 0.10 – 0.35 s                                                  |
| Peticiones para el histórico | 1719                                                           |
| `ETag`                       | **No** envía                                                   |
| `Last-Modified`              | **No** envía                                                   |
| `Cache-Control`              | **No** envía                                                   |
| HTTP 404                     | Correcto, página "Página no encontrada" sin `article.pelicula` |

La ausencia de cabeceras de revalidación es lo que obliga a la estrategia de cache en
disco (ADR-010). Si las enviara, la incrementalidad podría ser más fina.

---

## Límites y honestidad

- **Los datos son de la Academia de Cine**, no nuestros. Los datos de las fichas los
  aportan las productoras, como dice el propio pie de la web.
- **La fuente puede tener errores**, y hemos encontrado varios. Están documentados en
  `decisions.md` y se detectarán automáticamente en la Fase 6.
- **El sitio puede cambiar.** Si el HTML cambia, los tests de parsing lo detectarán antes de
  que se entere nadie. Esa es una de las razones principales para tenerlos.
- **Es un snapshot.** Los Goya 2026 ya se han celebrado, pero la 41 edición aún no. Cuando
  se celebre, `python -m goya_scraper` lo detectará y la añadirá sin tocar código.