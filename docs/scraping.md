# Cómo funciona el scraping

Recorrido de las ediciones, rate limiting, caché, errores e incrementalidad.

---

## 1. Descubrir las ediciones

Se pide la home y se extraen los enlaces `/{n}-edicion/` junto con su año.

El HTML trae un bloque `ol.lista-anios__lista` con los 40 años y su edición:

```html
<li class="lista-anios__anio">
    <a href="/40-edicion/">2026</a>
</li>
<li class="lista-anios__anio">
    <a href="/39-edicion/">2025</a>
</li>
```

Se leen **edition y año de la fuente**, no se calculan. Aunque se cumple
`año = edición + 1986` en las 40 ediciones sin una sola excepción, leerlo es más honesto
que suponerlo: si mañana se publica un número de edición distinto al esperado, funcionaría
igual.

Coste: **1 petición**.

---

## 2. Recorrer las ediciones

Para cada edición pendiente se pide:

```
https://www.premiosgoya.com/{n}-edicion/nominaciones/
```

**Una sola página por edición.** No hay paginación: las 40 ediciones caben enteras en su
página. Se comprobó en las 40: el número de filas de nominación (4050) cuadra exactamente
con lo que Esperábamos de un listado completo, y no aparece ningún control de paginación.

La estructura es:

```
div.peliculas__listado--nominaciones
└── section.categoria-de-peliculas        ← una por categoría
    ├── h1.categoria-de-peliculas__titulo    ← "Mejor dirección"
    └── ul.lista-de-peliculas
        └── li.lista-de-peliculas__pelicula  ← una por nominación
            ├── div.lista-de-peliculas__cartel > a[href]   ← SLUG de la película
            ├── div.lista-de-peliculas__datos
            │   ├── img[title^="Ganadora"]                 ← ¿ganó?
            │   ├── h2.lista-de-peliculas__titulo > a       ← acreditado
            │   └── div.lista-de-peliculas__texto > p       ← nota
```

**El detalle que más importa:** el `href` del cartel es **siempre** la película, mientras
que el texto del `h2` es la persona acreditada. Hay que usar el `href` para identificar la
película y el texto del `h2` para el acreditado. Confundirlos da como resultado 1678
"directores".

Coste: **40 peticiones**. Aporta las 4050 nominaciones.

---

## 3. Identificar al ganador

```python
won = li.select_one('img[title^="Ganadora"]') is not None
```

Semántico, estable y verificable (ADR-006). Se han localizado **1027 marcas de ganador**
en las 40 ediciones.

Detalle de implementación: el `img` del ganador es un hermano del `h2` dentro del mismo
`li`, así que el selector debe limitarse al `li` actual. Si se buscara en todo el
documento, cualquier marcado en la página contaminaría el resultado.

---

## 4. Recorrer las películas

De las 4050 nominaciones se extraen los `slug` únicos: **1678**.

Para cada uno se pide su ficha:

```
https://www.premiosgoya.com/pelicula/{slug}/
```

Aporta país, dirección, guion, reparto, sinopsis, duración y título original.

**Verificación de que la respuesta es lo que esperamos:** se comprueba que exista
`article.pelicula`. Una página 404 del sitio devuelve 404 real y **no** la tiene. Es una
comprobación barata que evita guardar un error como si fuera una película.

Coste: **1678 peticiones**.

---

## 5. Ensamblado

Las nominaciones de una edición se agrupan por `slug` y se fusionan con la ficha:

```python
movies[slug].nominations.extend(nominations_de_la_edicion)
```

Como ninguna película aparece en dos ediciones (verificado), en la práctica cada ficha se
visita una vez. Pero el modelo y el código lo permitirían sin cambios si algún día una
película compitiera en dos ediciones: simplemente se concatenarían las listas y se
sumarían los totales.

---

## Rate limiting

| Parámetro | Valor | Motivo |
|---|---|---|
| Pausa mínima entre peticiones | **1.2 s** | Educationado. El sitio responde en 0.1–0.35 s, así que es unas 4 veces más lento de lo necesario. |
| `timeout` de conexión | 10 s | |
| `timeout` de lectura | 30 s | |
| Reintentos | 3 | Solo ante error de red o HTTP 5xx. |
| Espera entre reintentos | 2 s, 4 s, 8 s | Espera creciente. |
| `User-Agent` | `goya-scraper/0.1 (+https://github.com/JavierHernandezSanchez/goya-scraper)` | Identificable, con contacto. |

**Total estimado la primera vez:** 1719 × 1.2 s ≈ **35 minutos**.

Los reintentos no están contados en esa cifra: solo suman si el servidor falla, y con
una tasa de acierto del 100% no suman nada.

**Sin concurrencia.** Podríamos hacerlo 5 veces más rápido con hilos, y el servidor se
enterraría de peticiones. El proyecto va educado. La profundidad de la backlog es
irrelevante aquí.

**Los aciertos de caché NO hacen `sleep`.** Servir desde disco no toca el servidor, así que
no hay nada que ser educado. Este texto decía antes lo contrario; era un error: dormir
cuando no hay petición solo haría que una ejecución cacheada tardase 35 minutos sin
motivo. Hay un test que falla si se duerme en un acierto de caché.

---

## Caché

```
cache/
├── home.html                  ← índice de ediciones
├── edicion_1.html             ← nominaciones de la edición 1
├── edicion_2.html
├── ...
└── pelicula_el-buen-patron.html   ← ficha de cada película
```

Regla: **si el fichero existe, no hay petición.** Sin condiciones, sin `ETag`, sin
`Last-Modified` (que además el servidor no envía — ADR-010).

Consecuencias:

- **La segunda ejecución hace 0 peticiones**, incluso con la pausa activa.
- Los tests de parsing leen HTML real desde `cache/` o desde `tests/fixtures/`, sin red.
- El proceso se puede interrumpir y reanudar sin perder trabajo.

El nombre del fichero es una versión sanitizada del `slug`; nunca se construye una ruta a
partir de datos sin limpiar.

Para forzar una resincronización completa:

```bash
rm -rf cache/
```

---

## Gestión de errores

El principio: **un fallo individual no detiene el proceso**.

| Situación | Qué hace |
|---|---|
| Error de red (timeout, DNS) | 3 reintentos, esperando 2 s, 4 s y 8 s. Si fallan, `ERROR` y se continúa con la siguiente película. |
| HTTP 5xx | 3 reintentos con la misma espera. Solo se reintenta un 5xx **realmente de servidor**: `{500, 502, 503, 504}`. |
| robots.txt prohíbe la URL | `RobotsDisallowed`. No se pide. Se registra y se continúa. |
| HTTP 404 | **No se reintenta** (reintentar un 404 es tiempo perdido). Se registra y se continúa. |
| HTTP 403 / 429 | **No se reintenta.** Se registra como `WARNING`. El scraper no intenta sortear nada. Si un sitio empieza a bloquear, es su derecho y hay que parar. |
| HTML inesperado (falta el contenedor esperado) | `ERROR` con detalle de qué faltaba, se registra en `data_quality.issues` y se continúa. |
| Fichero ilegible | `ERROR` y se omite la entrada. |

**Se guarda después de CADA edición, no solo al final.** El recorrido completo son unos
35 minutos; si el proceso se corta en la edición 30, sin esto se perderían las 29
anteriores. Cuesta unas 40 escrituras de unos pocos MB: nada.

Una edición que falla **no** se anota en `editions_scraped`, así que la siguiente
ejecución la vuelve a intentar. Una que sí termina, sí.

Al final se escribe igualmente `movies.json` con lo que se haya conseguido, más un resumen
en el log: cuántas películas, cuántas nominaciones, cuántas ediciones, y cuántas fallaron.

---

## Incrementalidad

Resumido, porque enADR-010 está el porqué:

1. Al arrancar se lee `data/movies.json` y se ve qué ediciones hay ya.
2. Se pide la home para saber qué ediciones existen (1 petición, cacheada).
3. Se procesan **solo las ediciones nuevas**.
4. De cada edición, solo las películas cuya ficha no esté en caché.
5. Se fusiona lo nuevo con lo ya existente y se reescribe el fichero.

```bash
python -m goya_scraper     # 1ª vez: ~35 min, 1719 peticiones
python -m goya_scraper     # 2ª vez: segundos, 0 peticiones
```

Y cuando se celebre la 41 edición, `python -m goya_scraper` la añade sin tocar código.

**Límite honesto:** si la Academia **cambia** los datos de una edición ya descargada, el
scraper no se entera, porque está en caché. Se arregla con `rm -rf cache/`. Es una
decisión consciente: incrementalidad simple frente a revalidación fina que aquí ni
siquiera es posible, porque el servidor no manda `ETag` ni `Last-Modified`.

---

## Recuperación ante una interrupción

Esto no estaba en el diseño original y salió de ver el recorrido en marcha.

**Guardamos `movies.json` después de cada edición, no solo al final.** El recorrido
completo son ~35 minutos repartidos en 1719 peticiones. Guardar solo al final significa
que un corte de red en la edición 30 tira las 29 anteriores. Cuesta ~40 escrituras de
pocos MB: irrelevante frente a perder media hora de trabajo ajeno.

Además:

- **Una edición fallida no se registra** en `editions_scraped`, así que la siguiente
  ejecución la reintenta sola.
- **Una edición terminada sí se registra**, así que no se vuelve a pedir ni aunque se
  borre la caché.
- **`Ctrl+C` es seguro.** Lo anterior ya está en `movies.json` y en `cache/`.

Probado de verdad: una ejecución cortada con `timeout` a los 5 minutos había dejado 9
ediciones completas en el disco, y la siguiente resumedió exactamente donde estaba, sin
volver a pedir ni una página ya descargada.

---

## Aviso sobre `robots.txt`

Se comprueba en cada ejecución con `urllib.robotparser`, la librería estándar. En este
sitio `robots.txt` da 404, que se interpreta correctamente como "sin restricciones". Se lee
**una sola vez** por cliente y se cachea en memoria.

Pero el código lo comprueba igualmente. Es lo que hace que el proyecto sea un extractor
*educado* en lugar de uno que simplemente no está bloqueado hoy.

Tres casos, por si el día que viene el sitio cambia:

| Situación | Qué hace |
|---|---|
| `robots.txt` = 404 | Sin restricciones, se sigue. |
| `robots.txt` = 200 | Se aplica. Una URL prohibida **no se pide**: `RobotsDisallowed`. |
| `robots.txt` ilegible o da error | Se avisa por log y se sigue **sin** restricciones. |

El último caso es deliberado: si no podemos leer el `robots.txt` no vamos a paralizar un
dataset por ello, pero tampoco vamos a fingir que lo hemos comprobado sin decirlo.

---

## Lo que NO hace este scraper

- No salta CAPTCHAs ni medidas anti-bot.
- No usa proxies, ni rotación de IP, ni fingerprints de navegador.
- No reintenta 403 ni 429.
- No va en paralelo.
- No pide más de una vez la misma URL en la misma ejecución.
- No accede a `academiadecine.com` ni a ninguna fuente externa.

Cada uno de esos puntos sería, por separado, la diferencia entre un proyecto que se puede
publicar en GitHub y uno que no.