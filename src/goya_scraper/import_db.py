"""Import data/movies.json into SQLite.

Reads a document, writes a database. Knows about both shapes and neither domain:
what a Goya award *is* comes from credited_kinds.py and persons.py, what a film
*is* comes from the document.

The import rebuilds the database from scratch inside one transaction (ADR-035).
That makes it reproducible, so importing the same JSON twice gives the same file,
and it makes every row of a run either land or not land: the transaction rolls
back as a whole on failure.

What the rollback does **not** protect is the previous database, because the file
is deleted before the schema is created. After a failed import you get a valid
empty database, not the one you had. Re-running the import is the recovery, which
is why the whole thing is a single reproducible command.

The JSON is only ever read. movies.json stays the source of truth.

Run it with:

    python -m goya_scraper.import_db
"""

import argparse
import hashlib
import logging
import sqlite3

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import db, storage
from .credited_kinds import credited_kind
from .persons import canonical_name

log = logging.getLogger(__name__)

IMPORTER_VERSION = "1"

DEFAULT_JSON = storage.DEFAULT_PATH
DEFAULT_DB = db.DEFAULT_PATH


class DocumentNotImportable(RuntimeError):
    """The document cannot be imported as it stands."""


@dataclass
class ImportReport:
    """What the import wrote, and what looked wrong on the way."""

    editions: int = 0
    categories: int = 0
    countries: int = 0
    movies: int = 0
    persons: int = 0
    person_aliases: int = 0
    movie_credits: int = 0
    movie_countries: int = 0
    nominations: int = 0
    nomination_credits: int = 0
    resolved_credits: int = 0
    unresolved_credits: int = 0
    reported_awards: int = 0
    awards: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def render(self) -> str:
        lines = [
            f"ediciones        {self.editions:>6d}",
            f"categorias       {self.categories:>6d}",
            f"peliculas        {self.movies:>6d}",
            f"personas         {self.persons:>6d}   (aliases {self.person_aliases})",
            f"creditos ficha   {self.movie_credits:>6d}",
            f"creditos pais    {self.movie_countries:>6d}",
            f"nominaciones     {self.nominations:>6d}   (premios {self.awards})",
            f"creditos nom.    {self.nomination_credits:>6d}"
            f"   ({self.resolved_credits} con persona,"
            f" {self.unresolved_credits} sin)",
            f"premios ficha    {self.reported_awards:>6d}",
        ]
        if self.problems:
            lines.append("")
            lines.append(f"{len(self.problems)} problema(s):")
            lines.extend(f"  - {problem}" for problem in self.problems)
        return "\n".join(lines)


def import_file(
    json_path: Path = DEFAULT_JSON, db_path: Path = DEFAULT_DB
) -> ImportReport:
    """Read the JSON from disk and import it, recording its hash.

    Reading the bytes first is deliberate: the hash has to describe the file that
    was actually imported, and storage.load returns a parsed document, not the
    bytes behind it.
    """
    json_path = Path(json_path)
    if not json_path.exists():
        raise DocumentNotImportable(
            f"{json_path} no existe. Ejecuta antes el scraper."
        )
    raw = json_path.read_bytes()
    document = storage.load(json_path)
    return import_document(document, db_path, json_bytes=raw)


def import_document(
    document: dict,
    path: Path = DEFAULT_DB,
    *,
    json_bytes: bytes | None = None,
    started_at: str | None = None,
) -> ImportReport:
    """Write `document` into a fresh database at `path`."""
    meta = document.get("_meta") or {}
    db.create_database(path, overwrite=True)
    connection = db.connect(path)
    try:
        return _write(
            connection,
            document,
            meta,
            started_at or _now(),
            hashlib.sha256(json_bytes).hexdigest() if json_bytes is not None else None,
        )
    finally:
        connection.close()


# ---------------------------------------------------------------- writing ----


def _write(
    connection: sqlite3.Connection,
    document: dict,
    meta: dict,
    stamp: str,
    digest: str | None,
) -> ImportReport:
    report = ImportReport()
    movies = document.get("movies") or []
    nominations = [
        (movie, nomination)
        for movie in movies
        for nomination in (movie.get("goya") or {}).get("nominations") or []
    ]
    report.editions = len({n["edition"] for _, n in nominations})
    report.movies = len(movies)

    # One transaction for everything. IMMEDIATE takes the write lock now instead
    # of at the first INSERT, so nothing partial is ever left behind.
    connection.execute("BEGIN IMMEDIATE")
    try:
        edition_ids = _write_editions(connection, nominations)
        category_ids, category_kinds = _write_categories(connection, nominations, report)
        country_ids = _write_countries(connection, movies, report)
        person_ids = _write_persons(connection, movies, nominations)
        movie_ids = _write_movies(connection, movies)
        _write_movie_credits(connection, movies, person_ids, movie_ids)
        _write_movie_countries(connection, movies, country_ids, movie_ids)
        _write_nominations(
            connection,
            nominations,
            movie_ids,
            edition_ids,
            category_ids,
            category_kinds,
            person_ids,
            report,
        )
        _write_reported_awards(connection, movies, movie_ids, report)
        _fill_counts(connection, report)
        _write_meta(connection, meta, document, stamp, digest, report)
        connection.execute("ANALYZE")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return report


def _write_editions(connection, nominations) -> dict[int, int]:
    """(edition, ceremony_year) pairs, sorted so the ids are stable.

    The year is read from the document, never computed from the number, even
    though it equals number + 1986 in all 40 editions.
    """
    found: dict[int, int] = {}
    for _, nomination in nominations:
        found[nomination["edition"]] = nomination["ceremony_year"]

    for number in sorted(found):
        # id == number: the edition number is 1..40 with no gaps, so using it as
        # the id makes the mapping trivially checkable.
        connection.execute(
            "INSERT INTO goya_edition (id, number, ceremony_year) VALUES (?, ?, ?)",
            (number, number, found[number]),
        )
    return {number: number for number in found}


def _write_categories(connection, nominations, report: ImportReport):
    """The canonical categories and the curated kind of each.

    A category with no known kind is refused rather than guessed. The importer
    must stop and ask, because the alternative is turning a film title into a
    person.
    """
    names = sorted({n["category"] for _, n in nominations})
    kinds = {name: credited_kind(name) for name in names}
    known = {}
    for index, name in enumerate(names, start=1):
        if kinds[name] is None:
            report.problems.append(
                f"categoria sin credited_kind: {name!r}. Sus nominaciones se "
                "omiten; anade la categoria a credited_kinds.py y reimporta."
            )
            continue
        connection.execute(
            "INSERT INTO category (id, name, credited_kind) VALUES (?, ?, ?)",
            (index, name, kinds[name]),
        )
        known[name] = index
    report.categories = len(known)
    return known, kinds


def _write_countries(connection, movies, report: ImportReport) -> dict[str, int]:
    names = sorted({c for movie in movies for c in (movie.get("countries") or [])})
    ids = {}
    for index, name in enumerate(names, start=1):
        ids[name] = index
        connection.execute(
            "INSERT INTO country (id, name) VALUES (?, ?)", (ids[name], name)
        )
    report.countries = len(names)
    return ids


def _write_persons(connection, movies, nominations) -> dict[str, int]:
    """Every spelling the source used, resolved to one row per real human.

    Names come from two places that barely overlap: 4322 people appear only on a
    film page and 910 only in a nomination. Both are kept, which is the only
    reason the technical crew survives into the database at all.
    """
    aliases: set[str] = set()
    for movie in movies:
        credits = movie.get("credits") or {}
        for role in ("directors", "screenwriters", "cast"):
            aliases.update(credits.get(role) or [])
    for _, nomination in nominations:
        if credited_kind(nomination["category"]) == "person":
            aliases.update(nomination["credited"])

    canonicals = sorted({canonical_name(alias) for alias in aliases})
    person_ids = {name: index for index, name in enumerate(canonicals, start=1)}
    for name, index in person_ids.items():
        connection.execute("INSERT INTO person (id, name) VALUES (?, ?)", (index, name))
    for alias in sorted(aliases):
        connection.execute(
            "INSERT INTO person_alias (alias, person_id) VALUES (?, ?)",
            (alias, person_ids[canonical_name(alias)]),
        )
    return person_ids


def _write_movies(connection, movies) -> dict[str, int]:
    ids: dict[str, int] = {}
    for index, movie in enumerate(sorted(movies, key=lambda m: m["slug"]), start=1):
        quality = movie.get("data_quality") or {}
        reported = quality.get("reported_by_source")
        connection.execute(
            "INSERT INTO movie (id, slug, title, title_original, synopsis, "
            "duration_minutes, producers_raw, countries_raw, detail_status, "
            "reported_nominations, reported_awards) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                index,
                movie["slug"],
                movie["title"],
                movie.get("title_original"),
                movie.get("synopsis"),
                movie.get("duration_minutes"),
                (movie.get("credits") or {}).get("producers_raw"),
                movie.get("countries_raw"),
                quality.get("detail_status", "ok"),
                # A page we never read has no reported counts. Zero would be a
                # different claim: that the page said the film won nothing, which
                # is what two films in this dataset say (ADR-014).
                reported.get("nominations") if reported else None,
                reported.get("awards") if reported else None,
            ),
        )
        ids[movie["slug"]] = index
    return ids


def _write_movie_credits(connection, movies, person_ids, movie_ids) -> None:
    roles = {
        "directors": "director",
        "screenwriters": "screenwriter",
        "cast": "cast",
    }
    for movie in sorted(movies, key=lambda m: m["slug"]):
        credits = movie.get("credits") or {}
        for key, role in roles.items():
            for position, name in enumerate(credits.get(key) or [], start=1):
                connection.execute(
                    "INSERT INTO movie_credit (movie_id, person_id, role, position) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        movie_ids[movie["slug"]],
                        person_ids[canonical_name(name)],
                        role,
                        position,
                    ),
                )


def _write_movie_countries(connection, movies, country_ids, movie_ids) -> None:
    for movie in sorted(movies, key=lambda m: m["slug"]):
        for position, name in enumerate(movie.get("countries") or [], start=1):
            connection.execute(
                "INSERT INTO movie_country (movie_id, country_id, position) "
                "VALUES (?, ?, ?)",
                (movie_ids[movie["slug"]], country_ids[name], position),
            )


def _write_nominations(
    connection,
    nominations,
    movie_ids,
    edition_ids,
    category_ids,
    category_kinds,
    person_ids,
    report: ImportReport,
) -> None:
    """One row per film competing for one award: the heart of the model.

    Ordered by slug, category and edition so the ids depend only on the data.
    The credits themselves do not enter the ordering: credited is a list, and
    sorting by a list is not something this needs.
    """
    ordered = sorted(
        nominations,
        key=lambda pair: (pair[0]["slug"], pair[1]["category"], pair[1]["edition"]),
    )

    for (movie, nomination) in ordered:
        category = nomination["category"]
        if category not in category_ids:
            report.problems.append(
                f"nominacion omitida: {movie['slug']!r} / {category!r} "
                f"(edicion {nomination['edition']}), categoria sin credited_kind"
            )
            continue

        resolved = _resolve_credits(nomination, category_kinds[category], person_ids)
        row_id = report.nominations + 1
        connection.execute(
            "INSERT INTO nomination (id, movie_id, edition_id, category_id, "
            "category_raw, won, note, credit_fingerprint) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row_id,
                movie_ids[movie["slug"]],
                edition_ids[nomination["edition"]],
                category_ids[category],
                nomination["category_raw"],
                1 if nomination["won"] else 0,
                nomination.get("note"),
                _fingerprint(resolved),
            ),
        )
        for position, (text, person) in enumerate(resolved, start=1):
            connection.execute(
                "INSERT INTO nomination_credit (nomination_id, position, "
                "credit_text, person_id) VALUES (?, ?, ?, ?)",
                (row_id, position, text, person),
            )
            report.nomination_credits += 1
            if person is None:
                report.unresolved_credits += 1
            else:
                report.resolved_credits += 1

        report.nominations += 1
        report.awards += 1 if nomination["won"] else 0


def _resolve_credits(nomination, kind, person_ids) -> list[tuple[str, int | None]]:
    """Pair each credited string with the person it names, when it names one.

    Only a 'person' category resolves. In a 'work' category the string is the
    film's own title, already reachable through nomination.movie_id, and joining
    on it would be wrong: 8 fragments coincide with a *different* film's title. In
    a 'song' category it is a title and its composers in one string.
    """
    resolved = []
    for text in nomination["credited"]:
        if kind != "person":
            resolved.append((text, None))
            continue
        person = person_ids.get(canonical_name(text))
        if person is None:
            log.warning(
                "sin persona para %r (%s, edicion %s)",
                text,
                nomination["category"],
                nomination["edition"],
            )
        resolved.append((text, person))
    return resolved


def _fingerprint(resolved) -> str:
    """The natural key of a nomination, in a form the engine can police.

    Person credits are keyed by id, not by name, so correcting a spelling does
    not change the fingerprint. Work and song credits are keyed by text because
    there is nothing else to key on.
    """
    return "|".join(f"p:{pid}" if pid else f"t:{text}" for text, pid in resolved)


def _write_reported_awards(connection, movies, movie_ids, report) -> None:
    """What each film page claimed, kept apart from what the edition says.

    No row at all means the page registered nothing. That is not the same as an
    empty list, and not the same as a zero: two films say zero and the edition
    awarded them anyway.
    """
    for movie in sorted(movies, key=lambda m: m["slug"]):
        quality = movie.get("data_quality") or {}
        reported = quality.get("reported_by_source") or {}
        categories = reported.get("award_categories")
        if categories is None:
            continue
        for position, raw in enumerate(categories, start=1):
            connection.execute(
                "INSERT INTO reported_award (movie_id, position, category_raw) "
                "VALUES (?, ?, ?)",
                (movie_ids[movie["slug"]], position, raw),
            )
            report.reported_awards += 1


def _fill_counts(connection, report) -> None:
    """Ask the database what landed, rather than trusting our own arithmetic.

    Four of the counts cannot be derived while writing: they come from tables
    whose size is only known once every row is in. Counting afterwards means the
    report describes the database, not our intentions.
    """
    for field_name, table in (
        ("persons", "person"),
        ("person_aliases", "person_alias"),
        ("movie_credits", "movie_credit"),
        ("movie_countries", "movie_country"),
    ):
        setattr(
            report,
            field_name,
            connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"],
        )


def _write_meta(connection, meta, document, stamp, digest, report) -> None:
    """Provenance: which JSON, when, and what actually landed."""
    counts = meta.get("counts") or {}
    connection.execute(
        "INSERT INTO dataset_meta VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            meta.get("schema_version", storage.SCHEMA_VERSION),
            meta.get("source", ""),
            meta.get("generated_at") or "",
            report.editions,
            report.movies,
            report.nominations,
            report.awards,
            report.categories,
        ),
    )
    connection.execute(
        "INSERT INTO import_run (id, started_at, finished_at, status, "
        "importer_version, json_schema_version, json_generated_at, json_sha256, "
        "movies, nominations, awards, persons, notes) "
        "VALUES (?, ?, ?, 'ok', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            stamp,
            _now(),
            IMPORTER_VERSION,
            meta.get("schema_version", storage.SCHEMA_VERSION),
            meta.get("generated_at") or "",
            digest or "",
            report.movies,
            report.nominations,
            report.awards,
            report.persons,
            "\n".join(report.problems) or None,
        ),
    )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    """`python -m goya_scraper.import_db [json] [db]`."""
    parser = argparse.ArgumentParser(
        prog="python -m goya_scraper.import_db",
        description="Importa data/movies.json en una base de datos SQLite.",
    )
    parser.add_argument(
        "json",
        nargs="?",
        type=Path,
        default=DEFAULT_JSON,
        help=f"documento a importar (por defecto {DEFAULT_JSON})",
    )
    parser.add_argument(
        "db",
        nargs="?",
        type=Path,
        default=DEFAULT_DB,
        help=f"base de datos a escribir (por defecto {DEFAULT_DB})",
    )
    arguments = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        report = import_file(arguments.json, arguments.db)
    except DocumentNotImportable as error:
        print(f"error: {error}")
        return 1

    print(report.render())
    print(f"\nescrito en {arguments.db}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())