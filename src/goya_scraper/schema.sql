-- ============================================================================
-- Esquema de la base de datos de los Premios Goya.
--
-- Dos ideas en todas las tablas:
--
-- 1. Claves surrogate con el identificador del servidor como restriccion.
--    movie.id es un entero nuestro; movie.slug es lo que dio el servidor.
--    El slug puede cambiar; el entero no.
--
-- 2. STRICT en todo. SQLite es de tipado dinamico y guardaria el texto
--    '105 anos' en una columna de duracion. STRICT lo convierte en error.
--    Necesita SQLite 3.37+.
--
-- Ordenado para que las tablas referenciadas vayan primero, asi que tambien
-- funciona como script:
--
--     sqlite3 data/goya.db < src/goya_scraper/schema.sql
-- ============================================================================


-- =========================================================================
-- 1. Procedencia. Sin relacion con el dominio.
-- =========================================================================

CREATE TABLE dataset_meta (
    -- CHECK (id = 1) es lo que hace que sea de una sola fila.
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    schema_version INTEGER NOT NULL,
    source         TEXT    NOT NULL,
    generated_at   TEXT    NOT NULL,
    editions       INTEGER NOT NULL,
    movies         INTEGER NOT NULL,
    nominations    INTEGER NOT NULL,
    awards         INTEGER NOT NULL,
    categories     INTEGER NOT NULL
) STRICT;

CREATE TABLE import_run (
    id                  INTEGER PRIMARY KEY,
    started_at          TEXT    NOT NULL,
    finished_at         TEXT,
    status              TEXT    NOT NULL CHECK (status IN ('ok', 'failed')),
    importer_version    TEXT    NOT NULL,
    json_schema_version INTEGER NOT NULL,
    json_generated_at   TEXT    NOT NULL,
    -- Permite saber si la BD se built con el JSON que tenemos ahora.
    json_sha256         TEXT    NOT NULL,
    movies              INTEGER,
    nominations         INTEGER,
    awards              INTEGER,
    persons             INTEGER,
    notes               TEXT
) STRICT;


-- =========================================================================
-- 2. Entidades del nucleo.
-- =========================================================================

CREATE TABLE goya_edition (
    id            INTEGER PRIMARY KEY,
    -- 'number' es lo que dice la URL (/36-edicion/).
    -- ceremony_year se guarda leido, no calculado, aunque en las 40 ediciones
    -- valga number + 1986: leer no cuesta nada y sigue siendo correcto.
    number        INTEGER NOT NULL UNIQUE CHECK (number BETWEEN 1 AND 200),
    ceremony_year INTEGER NOT NULL UNIQUE
                               CHECK (ceremony_year BETWEEN 1900 AND 2200)
) STRICT;

CREATE TABLE category (
    id            INTEGER PRIMARY KEY,
    name          TEXT    NOT NULL UNIQUE,
    -- Que imprime la web en la columna 'credited': una persona, la obra o una
    -- cancion. Curado en credited_kinds.py. Sin esto el importador tendria que
    -- adivinar, y adivinar aqui convierte un titulo en una persona.
    credited_kind TEXT    NOT NULL
        CHECK (credited_kind IN ('person', 'work', 'song'))
) STRICT;

CREATE TABLE country (
    id   INTEGER PRIMARY KEY,
    -- Nombres de la fuente, erratas incluidas: 'Fancia', 'Polinia', 'Extranjera'
    -- (que no es un pais) y 'Mexico Espana' (una lista que no se partio).
    -- No se corrigen aqui: curarlas es otra decision, revisable.
    name TEXT NOT NULL UNIQUE
) STRICT;

CREATE TABLE movie (
    id                   INTEGER PRIMARY KEY,
    -- Identidad del servidor (ADR-002). Nunca el titulo: doce titulos de este
    -- dataset son de dos slugs distintos ('alma'/'alma-2', 'roma'/'roma-2').
    slug                 TEXT    NOT NULL UNIQUE,
    title                TEXT    NOT NULL,
    title_original       TEXT,
    synopsis             TEXT,
    -- Los valores menores de 20 son reales: son cortos. 1156 de 1678 son NULL,
    -- que significa que la pagina no lo decia, no que no se pueda medir.
    duration_minutes     INTEGER CHECK (duration_minutes IS NULL
                                        OR duration_minutes > 0),
    -- Un string opaco a proposito. Los nombres de empresa llevan comas y aqui
    -- hay personas dentro: 'Lastor Media(Sergi Moreno,Tono Folguera Amoros)'.
    -- Un split ingenuo rompe los 297 valores con parentesis (ADR-008).
    producers_raw        TEXT,
    -- El texto sin normalizar, para que la normalizacion sea auditable.
    countries_raw        TEXT,
    detail_status        TEXT    NOT NULL
        CHECK (detail_status IN ('ok', 'not_found', 'error')),
    -- Lo que dice la ficha. Se guarda aunque lo podamos contar nosotros,
    -- porque es otra fuente y hay 6 peliculas donde las dos no coinciden
    -- (ADR-020, ADR-032).
    reported_nominations INTEGER,
    reported_awards      INTEGER,
    -- detail_status = 'ok' si y solo si leimos la ficha. Una peticion fallida no
    -- puede parecer una ficha que dice cero (ADR-014).
    CHECK ((detail_status = 'ok') = (reported_nominations IS NOT NULL)),
    CHECK ((detail_status = 'ok') = (reported_awards      IS NOT NULL))
) STRICT;

CREATE TABLE person (
    id   INTEGER PRIMARY KEY,
    -- La grafia que mostramos. La fuente no da id de persona, asi que este es el
    -- unico dato legible que hay.
    name TEXT    NOT NULL UNIQUE
) STRICT;

CREATE TABLE person_alias (
    -- Cada grafia de la fuente, tal cual. Guarda el mapeo hace reversibles las
    -- fusiones curadas: borra una fila y las dos grafias vuelven a ser dos
    -- personas, sin tocar codigo (ADR-027).
    alias     TEXT    PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE
) STRICT;


-- =========================================================================
-- 3. Relaciones.
-- =========================================================================

CREATE TABLE movie_credit (
    movie_id  INTEGER NOT NULL REFERENCES movie(id)  ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    -- Solo los tres roles gruesos que dice la ficha. El equipo tecnico (sonido,
    -- fotografia, vestuario) no tiene campo ahi y existe solo via
    -- nomination_credit.
    role      TEXT    NOT NULL CHECK (role IN ('director', 'screenwriter', 'cast')),
    position  INTEGER NOT NULL CHECK (position >= 1),
    -- 'role' va en la clave y no como columna: 1153 personas tienen dos roles en
    -- la misma pelicula, y una fila por persona no puede expresarlo.
    PRIMARY KEY (movie_id, person_id, role),
    -- Conserva el orden de la fuente sin permitir dos directores en el hueco 1.
    UNIQUE (movie_id, role, position)
) STRICT;

CREATE TABLE movie_country (
    movie_id   INTEGER NOT NULL REFERENCES movie(id)   ON DELETE CASCADE,
    country_id INTEGER NOT NULL REFERENCES country(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL CHECK (position >= 1),
    PRIMARY KEY (movie_id, country_id),
    UNIQUE (movie_id, position)
) STRICT;

CREATE TABLE nomination (
    id           INTEGER PRIMARY KEY,
    movie_id     INTEGER NOT NULL REFERENCES movie(id)        ON DELETE CASCADE,
    edition_id   INTEGER NOT NULL REFERENCES goya_edition(id) ON DELETE RESTRICT,
    category_id  INTEGER NOT NULL REFERENCES category(id)     ON DELETE RESTRICT,
    -- La etiqueta de ese ano. Va por fila y no como tabla de alias porque
    -- describe el ano de esta nominacion, no el premio (ADR-030).
    category_raw TEXT    NOT NULL,
    -- Ganar es propiedad de la nominacion, asi que es una columna y no hay tabla
    -- `award`. Cuatro ediciones tienen empate, una con tres ganadoras, y tres
    -- categorias no tienen ganador marcado; una tabla `award` con UNIQUE
    -- (edition_id, category_id) no podria contener eso (ADR-029).
    won          INTEGER NOT NULL CHECK (won IN (0, 1)),
    -- Texto libre. En 3001 de 4050 filas dice 'Por <titulo>', y en
    -- 'Mejor pelicula' contiene los productores.
    note         TEXT,
    -- La clave natural, escrita para que el motor vigile una doble importacion.
    -- (movie, edition, category) NO es unica: 46 ternas se repiten de verdad.
    -- Solo los creditos las distinguen (ADR-028).
    credit_fingerprint TEXT NOT NULL
) STRICT;

-- Se comprueba sobre los datos reales: 4050 filas, cero rechazos.
CREATE UNIQUE INDEX nomination_natural_key
    ON nomination (movie_id, edition_id, category_id, credit_fingerprint);

CREATE TABLE nomination_credit (
    nomination_id INTEGER NOT NULL REFERENCES nomination(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL CHECK (position >= 1),
    -- El texto de la fuente, literal. En las 10 categorias 'work' es un titulo
    -- partido por comas y por ' y ', asi que 'Dolor y gloria' esta guardado como
    -- ['Dolor', 'gloria']. El dano queda visible y nunca se une a una pelicula:
    -- 8 de esos fragmentos coinciden con el titulo de OTRA pelicula.
    credit_text   TEXT    NOT NULL,
    -- NULL en los 1355 creditos de categorias 'work' y 'song': son un titulo y
    -- una cancion con compositores, no personas. Los 3922 creditos de categorias
    -- 'person' se resuelven todos, y ningun titulo aparece en ellas.
    person_id     INTEGER REFERENCES person(id) ON DELETE RESTRICT,
    PRIMARY KEY (nomination_id, position)
) STRICT;

CREATE TABLE reported_award (
    movie_id     INTEGER NOT NULL REFERENCES movie(id) ON DELETE CASCADE,
    position     INTEGER NOT NULL CHECK (position >= 1),
    -- Etiqueta cruda, con la grafia del ano de esa pelicula. 'La nina de tus
    -- ojos' aparece como 'Mejor direccion artistica' mientras la edicion dio
    -- 'Mejor direccion de arte'. Comparar los dos lados necesita esta columna.
    category_raw TEXT    NOT NULL,
    -- Sin fila significa que la ficha no registro ningun premio. Distinto de una
    -- lista vacia, y distinto de reported_awards = 0, que es lo que dicen dos
    -- peliculas: El rey de la granja y Puerta del tiempo, ambas premiadas.
    PRIMARY KEY (movie_id, position)
) STRICT;


-- =========================================================================
-- 4. Vistas. Se recalcula en vez de almacenarse (ADR-031).
-- =========================================================================

CREATE VIEW movie_totals AS
SELECT m.id            AS movie_id,
       m.slug,
       m.title,
       COUNT(n.id)             AS total_nominations,
       COALESCE(SUM(n.won), 0) AS total_awards
FROM movie m
LEFT JOIN nomination n ON n.movie_id = m.id
GROUP BY m.id;


-- =========================================================================
-- 5. Indices.
--
-- Solo los que necesita una consulta real. Las PRIMARY KEY y las UNIQUE ya
-- crean sus propios indices, asi que esas columnas se omiten a proposito:
-- movie_credit esta indexada por (movie_id, person_id, role), que ya responde a
-- una busqueda por movie_id.
-- =========================================================================

CREATE INDEX idx_nomination_movie ON nomination(movie_id);
CREATE INDEX idx_nomination_category ON nomination(category_id, edition_id);
CREATE INDEX idx_nomination_edition ON nomination(edition_id);

-- Parcial: solo 1027 de 4050 filas son ganadoras, asi que este indice es cuatro
-- veces mas pequeno y sigue respondiendo a todas las consultas de ganadores.
CREATE INDEX idx_nomination_winners ON nomination(category_id, edition_id)
    WHERE won = 1;

CREATE INDEX idx_movie_credit_person ON movie_credit(person_id);
CREATE INDEX idx_nomination_credit_person ON nomination_credit(person_id);
CREATE INDEX idx_movie_country_country ON movie_country(country_id);
-- Indice normal, no UNIQUE: doce titulos son de dos slugs cada uno.
CREATE INDEX idx_movie_title ON movie(title);
CREATE INDEX idx_person_alias_person ON person_alias(person_id);